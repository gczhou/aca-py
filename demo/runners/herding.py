import asyncio
import json
import logging
import os
import sys
import time

from aiohttp import ClientError

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runners.agent_container import (  # noqa:E402
    arg_parser,
    create_agent_with_args,
    AriesAgent,
)
from runners.support.agent import (  # noqa:E402
    CRED_FORMAT_INDY,
    CRED_FORMAT_JSON_LD,
    SIG_TYPE_BLS,
)
from runners.support.utils import (  # noqa:E402
    log_msg,
    log_status,
    prompt,
    prompt_loop,
)


CRED_PREVIEW_TYPE = "https://didcomm.org/issue-credential/2.0/credential-preview"
SELF_ATTESTED = os.getenv("SELF_ATTESTED")
TAILS_FILE_COUNT = int(os.getenv("TAILS_FILE_COUNT", 100))

logging.basicConfig(level=logging.WARNING)
LOGGER = logging.getLogger(__name__)


class HerdingAgent(AriesAgent):
    def __init__(
        self,
        ident: str,
        http_port: int,
        admin_port: int,
        no_auto: bool = False,
        **kwargs,
    ):
        super().__init__(
            ident,
            http_port,
            admin_port,
            prefix="Herding",
            no_auto=no_auto,
            **kwargs,
        )
        self.connection_id = None
        self._connection_ready = None
        self.cred_state = {}
        # TODO define a dict to hold credential attributes
        # based on cred_def_id
        self.cred_attrs = {}

    async def detect_connection(self):
        await self._connection_ready
        self._connection_ready = None

    @property
    def connection_ready(self):
        return self._connection_ready.done() and self._connection_ready.result()


async def main(args):
    herding_agent = await create_agent_with_args(args, ident="herding")

    try:
        log_status(
            "#1 Provision an agent and wallet, get back configuration details"
            + (
                f" (Wallet type: {herding_agent.wallet_type})"
                if herding_agent.wallet_type
                else ""
            )
        )
        agent = HerdingAgent(
            "herding.agent",
            herding_agent.start_port,
            herding_agent.start_port + 1,
            genesis_data=herding_agent.genesis_txns,
            no_auto=herding_agent.no_auto,
            tails_server_base_url=herding_agent.tails_server_base_url,
            timing=herding_agent.show_timing,
            multitenant=herding_agent.multitenant,
            mediation=herding_agent.mediation,
            wallet_type=herding_agent.wallet_type,
			seed=herding_agent.seed,
        )

        if herding_agent.cred_type == CRED_FORMAT_INDY:
            herding_agent.public_did = True
            herding_schema_name = "degree schema"
            herding_schema_attrs = ["name", "date", "degree", "age", "timestamp"]
            await herding_agent.initialize(
                the_agent=agent,
                schema_name=herding_schema_name,
                schema_attrs=herding_schema_attrs,
            )
        elif herding_agent.cred_type == CRED_FORMAT_JSON_LD:
            herding_agent.public_did = True
            await herding_agent.initialize(the_agent=agent)
        else:
            raise Exception("Invalid credential type:" + herding_agent.cred_type)

        # generate an invitation for Alice
        await herding_agent.generate_invitation(display_qr=True, wait=True)

        exchange_tracing = False
        options = (
            "    (1) Issue Credential\n"
            "    (2) Send Proof Request\n"
            "    (3) Send Message\n"
            "    (4) Create New Invitation\n"
        )
        if herding_agent.revocation:
            options += "    (5) Revoke Credential\n" "    (6) Publish Revocations\n"
        if herding_agent.multitenant:
            options += "    (W) Create and/or Enable Wallet\n"
        options += "    (T) Toggle tracing on credential/proof exchange\n"
        options += "    (X) Exit?\n[1/2/3/4/{}{}T/X] ".format(
            "5/6/" if herding_agent.revocation else "",
            "W/" if herding_agent.multitenant else "",
        )
        async for option in prompt_loop(options):
            if option is not None:
                option = option.strip()

            if option is None or option in "xX":
                break

            elif option in "wW" and herding_agent.multitenant:
                target_wallet_name = await prompt("Enter wallet name: ")
                include_subwallet_webhook = await prompt(
                    "(Y/N) Create sub-wallet webhook target: "
                )
                if include_subwallet_webhook.lower() == "y":
                    created = await herding_agent.agent.register_or_switch_wallet(
                        target_wallet_name,
                        webhook_port=herding_agent.agent.get_new_webhook_port(),
                        public_did=True,
                        mediator_agent=herding_agent.mediator_agent,
                    )
                else:
                    created = await herding_agent.agent.register_or_switch_wallet(
                        target_wallet_name,
                        public_did=True,
                        mediator_agent=herding_agent.mediator_agent,
                    )
                # create a schema and cred def for the new wallet
                # TODO check first in case we are switching between existing wallets
                if created:
                    # TODO this fails because the new wallet doesn't get a public DID
                    await herding_agent.create_schema_and_cred_def(
                        schema_name=herding_schema_name,
                        schema_attrs=herding_schema_attrs,
                    )

            elif option in "tT":
                exchange_tracing = not exchange_tracing
                log_msg(
                    ">>> Credential/Proof Exchange Tracing is {}".format(
                        "ON" if exchange_tracing else "OFF"
                    )
                )

            elif option == "1":
                log_status("#13 Issue credential offer to X")

				if herding_agent.aip == 10:
                    # define attributes to send for credential
					 herding_agent.agent.cred_attrs[herding_agent.cred_def_id] = {
                    "name": "Alice Smith",
                    "date": "2018-05-28",
                    "degree": "Maths",
                    "age": "24",
                    "timestamp": str(int(time.time())),
                }

                cred_preview = {
                    "@type": CRED_PREVIEW_TYPE,
                    "attributes": [
                        {"name": n, "value": v}
                        for (n, v) in herding_agent.agent.cred_attrs[
                            herding_agent.cred_def_id
                        ].items()
                    ],
                }
                offer_request = {
                    "connection_id": herding_agent.agent.connection_id,
					"cred_def_id": herding_agent.cred_def_id,
                    "comment": f"Offer on cred def id {herding_agent.cred_def_id}",
                    "auto_remove": False,
                    "credential_preview": cred_preview,
                        "trace": exchange_tracing,
                    }
                    await herding_agent.agent.admin_POST(
                        "/issue-credential/send-offer", offer_request
                    )

                elif herding_agent.aip == 20:
                    if herding_agent.cred_type == CRED_FORMAT_INDY:
                        herding_agent.agent.cred_attrs[herding_agent.cred_def_id] = {
                            "name": "Alice Smith",
                            "date": "2018-05-28",
                            "degree": "Maths",
                            "age": "24",
                            "timestamp": str(int(time.time())),
                        }

                        cred_preview = {
                            "@type": CRED_PREVIEW_TYPE,
                            "attributes": [
                                {"name": n, "value": v}
                                for (n, v) in herding_agent.agent.cred_attrs[
                                    herding_agent.cred_def_id
                                ].items()
                            ],
                        }
                        offer_request = {
                            "connection_id": herding_agent.agent.connection_id,
                            "comment": f"Offer on cred def id {herding_agent.cred_def_id}",
                            "auto_remove": False,
                            "credential_preview": cred_preview,
                            "filter": {
                                "indy": {"cred_def_id": herding_agent.cred_def_id}
                            },
                            "trace": exchange_tracing,
                        }

                    elif herding_agent.cred_type == CRED_FORMAT_JSON_LD:
                        offer_request = {
                            "connection_id": herding_agent.agent.connection_id,
                            "filter": {
                                "ld_proof": {
                                    "credential": {
                                        "@context": [
                                            "https://www.w3.org/2018/credentials/v1",
                                            "https://w3id.org/citizenship/v1",
                                        ],
                                        "type": [
                                            "VerifiableCredential",
                                            "PermanentResident",
                                        ],
                                        "id": "https://credential.example.com/residents/1234567890",
                                        "issuer": herding_agent.agent.did,
                                        "issuanceDate": "2020-01-01T12:00:00Z",
                                        "credentialSubject": {
                                            "type": ["PermanentResident"],
                                            # "id": "<TODO need did:key of holder>",
                                            "givenName": "ALICE",
                                            "familyName": "SMITH",
                                            "gender": "Female",
                                            "birthCountry": "Bahamas",
                                            "birthDate": "1958-07-17",
                                        },
                                    },
                                    "options": {"proofType": SIG_TYPE_BLS},
                                }
                            },
                        }

                    else:
                        raise Exception(
                            f"Error invalid credential type: {herding_agent.cred_type}"
                        )

                    await herding_agent.agent.admin_POST(
                        "/issue-credential-2.0/send-offer", offer_request
                    )

                else:
                    raise Exception(f"Error invalid AIP level: {herding_agent.aip}")

            elif option == "2":
                log_status("#20 Request proof of degree from alice")
                if herding_agent.aip == 10:
                    req_attrs = [
                        {
                            "name": "name",
                            "restrictions": [{"schema_name": "degree schema"}],
                        },
                        {
                            "name": "date",
                            "restrictions": [{"schema_name": "degree schema"}],
                        },
                    ]
                    if herding_agent.revocation:
                        req_attrs.append(
                            {
                                "name": "degree",
                                "restrictions": [{"schema_name": "degree schema"}],
                                "non_revoked": {"to": int(time.time() - 1)},
                            },
                        )
                    else:
                        req_attrs.append(
                            {
                                "name": "degree",
                                "restrictions": [{"schema_name": "degree schema"}],
                            }
                        )
                    if SELF_ATTESTED:
                        # test self-attested claims
                        req_attrs.append(
                            {"name": "self_attested_thing"},
                        )
                    req_preds = [
                        # test zero-knowledge proofs
                        {
                            "name": "age",
                            "p_type": ">=",
                            "p_value": 18,
                            "restrictions": [{"schema_name": "degree schema"}],
                        }
                    ]
                    indy_proof_request = {
                        "name": "Proof of Education",
                        "version": "1.0",
                        "requested_attributes": {
                            f"0_{req_attr['name']}_uuid": req_attr
                            for req_attr in req_attrs
                        },
                        "requested_predicates": {
                            f"0_{req_pred['name']}_GE_uuid": req_pred
                            for req_pred in req_preds
                        },
                    }

                    if herding_agent.revocation:
                        indy_proof_request["non_revoked"] = {"to": int(time.time())}
                    proof_request_web_request = {
                        "connection_id": herding_agent.agent.connection_id,
                        "proof_request": indy_proof_request,
                        "trace": exchange_tracing,
                    }
                    await herding_agent.agent.admin_POST(
                        "/present-proof/send-request", proof_request_web_request
                    )
                    pass

                elif herding_agent.aip == 20:
                    if herding_agent.cred_type == CRED_FORMAT_INDY:
                        req_attrs = [
                            {
                                "name": "name",
                                "restrictions": [{"schema_name": herding_schema_name}],
                            },
                            {
                                "name": "date",
                                "restrictions": [{"schema_name": herding_schema_name}],
                            },
                        ]
                        if herding_agent.revocation:
                            req_attrs.append(
                                {
                                    "name": "degree",
                                    "restrictions": [
                                        {"schema_name": herding_schema_name}
                                    ],
                                    "non_revoked": {"to": int(time.time() - 1)},
                                },
                            )
                        else:
                            req_attrs.append(
                                {
                                    "name": "degree",
                                    "restrictions": [
                                        {"schema_name": herding_schema_name}
                                    ],
                                }
                            )
                        if SELF_ATTESTED:
                            # test self-attested claims
                            req_attrs.append(
                                {"name": "self_attested_thing"},
                            )
                        req_preds = [
                            # test zero-knowledge proofs
                            {
                                "name": "age",
                                "p_type": ">=",
                                "p_value": 18,
                                "restrictions": [{"schema_name": herding_schema_name}],
                            }
                        ]
                        indy_proof_request = {
                            "name": "Proof of Education",
                            "version": "1.0",
                            "requested_attributes": {
                                f"0_{req_attr['name']}_uuid": req_attr
                                for req_attr in req_attrs
                            },
                            "requested_predicates": {
                                f"0_{req_pred['name']}_GE_uuid": req_pred
                                for req_pred in req_preds
                            },
                        }

                        if herding_agent.revocation:
                            indy_proof_request["non_revoked"] = {"to": int(time.time())}
                        proof_request_web_request = {
                            "connection_id": herding_agent.agent.connection_id,
                            "presentation_request": {"indy": indy_proof_request},
                            "trace": exchange_tracing,
                        }

                    elif herding_agent.cred_type == CRED_FORMAT_JSON_LD:
                        proof_request_web_request = {
                            "comment": "test proof request for json-ld",
                            "connection_id": herding_agent.agent.connection_id,
                            "presentation_request": {
                                "dif": {
                                    "options": {
                                        "challenge": "3fa85f64-5717-4562-b3fc-2c963f66afa7",
                                        "domain": "4jt78h47fh47",
                                    },
                                    "presentation_definition": {
                                        "id": "32f54163-7166-48f1-93d8-ff217bdb0654",
                                        "format": {
                                            "ldp_vp": {"proof_type": [SIG_TYPE_BLS]}
                                        },
                                        "input_descriptors": [
                                            {
                                                "id": "citizenship_input_1",
                                                "name": "EU Driver's License",
                                                "schema": [
                                                    {
                                                        "uri": "https://www.w3.org/2018/credentials#VerifiableCredential"
                                                    },
                                                    {
                                                        "uri": "https://w3id.org/citizenship#PermanentResident"
                                                    },
                                                ],
                                                "constraints": {
                                                    "limit_disclosure": "required",
                                                    "fields": [
                                                        {
                                                            "path": [
                                                                "$.credentialSubject.familyName"
                                                            ],
                                                            "purpose": "The claim must be from one of the specified person",
                                                            "filter": {
                                                                "const": "SMITH"
                                                            },
                                                        },
                                                        {
                                                            "path": [
                                                                "$.credentialSubject.givenName"
                                                            ],
                                                            "purpose": "The claim must be from one of the specified person",
                                                        },
                                                    ],
                                                },
                                            }
                                        ],
                                    },
                                }
                            },
                        }

                    else:
                        raise Exception(
                            "Error invalid credential type:" + herding_agent.cred_type
                        )

                    await agent.admin_POST(
                        "/present-proof-2.0/send-request", proof_request_web_request
                    )

                else:
                    raise Exception(f"Error invalid AIP level: {herding_agent.aip}")

            elif option == "3":
                msg = await prompt("Enter message: ")
                await herding_agent.agent.admin_POST(
                    f"/connections/{herding_agent.agent.connection_id}/send-message",
                    {"content": msg},
                )

            elif option == "4":
                log_msg(
                    "Creating a new invitation, please receive "
                    "and accept this invitation using Alice agent"
                )
                await herding_agent.generate_invitation(display_qr=True, wait=True)

            elif option == "5" and herding_agent.revocation:
                rev_reg_id = (await prompt("Enter revocation registry ID: ")).strip()
                cred_rev_id = (await prompt("Enter credential revocation ID: ")).strip()
                publish = (
                    await prompt("Publish now? [Y/N]: ", default="N")
                ).strip() in "yY"
                try:
                    await herding_agent.agent.admin_POST(
                        "/revocation/revoke",
                        {
                            "rev_reg_id": rev_reg_id,
                            "cred_rev_id": cred_rev_id,
                            "publish": publish,
                        },
                    )
                except ClientError:
                    pass

            elif option == "6" and herding_agent.revocation:
                try:
                    resp = await herding_agent.agent.admin_POST(
                        "/revocation/publish-revocations", {}
                    )
                    herding_agent.agent.log(
                        "Published revocations for {} revocation registr{} {}".format(
                            len(resp["rrid2crid"]),
                            "y" if len(resp["rrid2crid"]) == 1 else "ies",
                            json.dumps([k for k in resp["rrid2crid"]], indent=4),
                        )
                    )
                except ClientError:
                    pass

        if herding_agent.show_timing:
            timing = await herding_agent.agent.fetch_timing()
            if timing:
                for line in herding_agent.agent.format_timing(timing):
                    log_msg(line)

    finally:
        terminated = await herding_agent.terminate()

    await asyncio.sleep(0.1)

    if not terminated:
        os._exit(1)


if __name__ == "__main__":
    parser = arg_parser(ident="herding", port=8020)
    args = parser.parse_args()

    ENABLE_PYDEVD_PYCHARM = os.getenv("ENABLE_PYDEVD_PYCHARM", "").lower()
    ENABLE_PYDEVD_PYCHARM = ENABLE_PYDEVD_PYCHARM and ENABLE_PYDEVD_PYCHARM not in (
        "false",
        "0",
    )
    PYDEVD_PYCHARM_HOST = os.getenv("PYDEVD_PYCHARM_HOST", "localhost")
    PYDEVD_PYCHARM_CONTROLLER_PORT = int(
        os.getenv("PYDEVD_PYCHARM_CONTROLLER_PORT", 5001)
    )

    if ENABLE_PYDEVD_PYCHARM:
        try:
            import pydevd_pycharm

            print(
                "Herding remote debugging to "
                f"{PYDEVD_PYCHARM_HOST}:{PYDEVD_PYCHARM_CONTROLLER_PORT}"
            )
            pydevd_pycharm.settrace(
                host=PYDEVD_PYCHARM_HOST,
                port=PYDEVD_PYCHARM_CONTROLLER_PORT,
                stdoutToServer=True,
                stderrToServer=True,
                suspend=False,
            )
        except ImportError:
            print("pydevd_pycharm library was not found")

    try:
        asyncio.get_event_loop().run_until_complete(main(args))
    except KeyboardInterrupt:
        os._exit(1)

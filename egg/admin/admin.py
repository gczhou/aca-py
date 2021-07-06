async def main(args):
    #初始化agent，启动各个网口监听



    #产生邀请generate_invitation

    pass

if __name__ == "__main__":
    parser = arg_parser()
    args = parser.parse_args()

    try:
        asyncio.get_event_loop().run_until_complete(main(args))
    except KeyboardInterrupt:
        os._exit(1)
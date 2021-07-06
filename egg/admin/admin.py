
from ..common.agent import EggAgent

class AdminAgent(EggAgent):
    def __init__(self) -> None:
        pass

    

async def main(args):
    #初始化agent，启动各个网口监听

    #产生一个进程，邀请generate_invitation，然后放置后台一直运行，如果接收到链接请求，则进行处理。

    #链接管理



    pass

if __name__ == "__main__":
    parser = arg_parser()
    args = parser.parse_args()

    try:
        asyncio.get_event_loop().run_until_complete(main(args))
    except KeyboardInterrupt:
        os._exit(1)
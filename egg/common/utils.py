import argparse

def arg_parser():
    """
    Standard command-line arguements.
    """
    parser = argparse.ArgumentParser()    
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=port,
        metavar=("<port>"),
        help="Choose the starting port number to listen on",
    )
    return parser
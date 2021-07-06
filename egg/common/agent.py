
class EggAgent:
    def __init__(
        self,
        http_port: int,
        admin_port: int,
        label: str = None,        
    ):
        self.http_port = http_port
        self.admin_port = admin_port
        self.label = label
    
class Agent(BaseAgent):
    pass


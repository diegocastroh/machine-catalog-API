from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser


def is_allowed_by_robots(robots_txt: str, user_agent: str, url: str) -> bool:
    parser = RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return parser.can_fetch(user_agent, url)


def robots_url_for(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

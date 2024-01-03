from aiohttp import ClientSession, ClientResponseError
from aiohttp_socks import ProxyConnector
from attrs import define
from enum import IntEnum
from typing import Optional
import random
import asyncio
import orjson
import asyncclick as click
from colorama import Fore, init, deinit
import re


API = "/api/v10/invites/{}?with_counts=1&with_expiration=1"

DISCORD_SERVER_RE = re.compile(
    r"(?:https?://)?(?:www.)?(?:discord.(?:gg|io|me|li)|discordapp.com/invite)/([^\s/]+?(?=\s))"
)
"""Slightly modified version of some of the regexes posted here: 
    https://reddit.com/r/regex/comments/jgubjz/discord_invite_regex/?rdt=42337
"""

# TODO Add support for TOR using python's stem library...

# requirements - asyncclick , orjson , aiohttp , aiohttp_socks, attrs , colorama

USERAGENTS =  ["Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:92.0) Gecko/20100101 Firefox/92.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.14; rv:93.0) Gecko/20100101 Firefox/93.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:91.0) Gecko/20100101 Firefox/91.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0",
    "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:94.0) Gecko/20100101 Firefox/94.0"]


class JoinRequirements(IntEnum):
    """intrepreted from discord's `verification_level` parameters"""
    UNKNOWN = 0
    """User doesn't have any security in place..."""

    NoVerifications = 1
    """User doesn't have to do anything special to get inside"""

    FiveMinuteWait = 2 
    """User must wait 5 minutes after making a discord account"""

    VerifiedEmailTenMinuteWait = 3
    """user must have a verified Email And Wait 10 minutes"""

    VerifiedPhoneNumber = 4 
    """user must have a verified phone number"""


class LockedFile:
    """A Sepcial file that can be written to..."""
    def __init__(self, file:str) -> None:
        self.file = file
        self._lock = asyncio.Lock()

    async def write(self, line:bytes):
        async with self._lock:
            with open(self.file, "ab") as fp:
                fp.write(line + b"\n")


def fail(url:str):
    print(Fore.RED + "[" + Fore.RESET + "-" + Fore.RED + f"] {url} does not exist..." + Fore.RESET)

def success(url:str, verification_level:int, population:str, title:str):
    print(Fore.GREEN + "[" +  Fore.RESET + "+" + Fore.GREEN + f"] {url}    Servername: {title}   Verification Level:{verification_level}    Population:{population}") 

def banner():
    init(True)
    print(Fore.LIGHTBLUE_EX + r"""

    ________   __                                                         
    \______ \ |__| ______ ______ ____ _____    ____   ____   ____ _______ 
     |    |  \|  |/  ___//  ___// ___\\__  \  /    \ /    \_/ __ \\_  __ \
     |    |   \  |\___ \ \___ \\  \___ / __ \_   |  \   |  \  ___/_|  | \/
    /_______  /__|____  \____  \\___  /____  /___|  /___|  /\___  /|__|   
            \/        \/     \/     \/     \/     \/     \/     \/        

            The Ultimate Discord Invite Scanner     0.0.1
                            By Calloc
    """ + Fore.RESET)

@define
class Invite:
    invite:str
    failed:bool = False
    json_data:dict = {}

    @property
    def json(self):
        return orjson.dumps(self.json_data)
    
    @property
    def verification_level(self) -> int:
        return self.json_data['guild']['verification_level']

    @property
    def url(self):
        return f"https://discord.gg/{self.invite}"

    @property
    def title(self):
        return self.json_data['guild']['name']

    @property
    def population(self):
        return self.json_data['approximate_member_count']

    def print(self):
        """Prints a report to the console..."""
        if self.failed:
            return fail(self.url)
        return success(self.url, self.verification_level, self.population, self.title)



class DiscordInviteResolver:
    def __init__(self, proxy:Optional[str] = None) -> None:
        self.client = ClientSession("https://discord.com", connector=ProxyConnector.from_url(proxy) if proxy else None)
        self.client.headers['User-Agent'] = random.choice(USERAGENTS)
        self.loop = asyncio.get_event_loop()

    def _parse(self, data:bytes) -> asyncio.Future[dict]:
        fut = self.loop.create_future()
        self.loop.call_soon(lambda x:fut.set_result(orjson.loads(x)), data)
        return fut

    async def resolve(self, invite:str):
        """Used for resolving invites"""
        try:
            async with self.client.get(API.format(invite), raise_for_status = True) as resp:
                i = Invite(invite, json_data=await self._parse(await resp.read()))
            return i
        except ClientResponseError:
            return Invite(invite, failed=True)

    def close(self):
        return self.client.close()

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        return await self.close()



class AsyncHandle:
    def __init__(self, func, threads: int = 2, queue_limit:int = None, timer:int = None) -> None:
        self.q = asyncio.Queue(maxsize=queue_limit if queue_limit else 0)
        self.func = func
        self.threads = threads
        self.workers = [asyncio.create_task(self.run()) for _ in range(threads)]
        self.timer = timer
        self.loop = asyncio.get_event_loop()
    
    async def add_async(self, *args, **kwargs):
        await self.q.put((args, kwargs))

    def add(self, *args, **kwargs):
        self.q.put_nowait((args, kwargs))

    async def join(self):
        """Joins all results together"""
        await self.q.join()
        for w in self.workers:
            await self.q.put(None)
        for w in self.workers:
            w.cancel()
            
    async def cancel(self):
        """Shuts down and kill all the workers and queues..."""
        for w in self.workers:
            await self.q.put(None)
            
        for w in self.workers:
            w.cancel()

    async def run(self):
        while True:
            ak = await self.q.get()
            if ak is None:
                break
            a, k = ak
            try:
                if self.timer is not None:
                    await asyncio.wait_for(self.func(*a, **k), self.timer)
                else:
                    await self.func(*a, **k)
            except Exception as e:
                self.loop.call_soon(print, e)
            self.q.task_done()

def match_or_ignore(i:str) -> str:
    try:
        return DISCORD_SERVER_RE.match(i).group(1) 
    except:
        return i

class CliResolver(DiscordInviteResolver):
    def __init__(self, threads:int = 2 , output:Optional[str] = None, proxy: Optional[str] = None, disable_printing:bool = False) -> None:
        super().__init__(proxy)
        self.output = LockedFile(output) if output else None
        self.threads = threads
        self.queue = AsyncHandle(self.resolve, threads, 100, 300)
        self.disable_printing = disable_printing

    async def resolve(self, invite: str):
        i = await super().resolve(invite)
        if not self.disable_printing:
            self.loop.call_soon(i.print)
        if self.output and not i.failed:
            await self.output.write(i.json)

    async def feed_invites(self, invites:list[str]):
        for i in invites:
            await self.queue.add_async(match_or_ignore(i))

    async def get_files(self, files:list[str]):
        for f in files:
            with open(f, "r") as r:
                for l in r:
                    await self.queue.add_async(l)

    async def wait(self):
        await self.queue.join()


@define
class Config:
    """Configuration inspired by twint makes it really easy to program your own tools with Disscan 
    for scanning out discord invites and returning bakc the invite data that is uncovered from it..."""
    proxy:Optional[str] = None
    invites:list[str] = []
    threads:int = 2 
    output:Optional[str] = None
    lists:list[str] = []
    """A list of paths to textfiles to either parse or other"""
    disable_color:bool = False
    disabale_printing:bool = False
    """If your running a python script of your own, you can optinally 
    turn off printing all together (excluding exceptions raised)"""

    async def run_async(self):
        if self.disable_color:
            init(strip=True)
        else:
            init(autoreset=True)
        async with CliResolver(self.threads, self.output, self.proxy, self.disabale_printing) as resolver:
            await resolver.feed_invites(self.invites)
            await resolver.get_files(self.lists)
            await resolver.wait()
    
    def run(self):
        asyncio.run()


@click.command()
@click.option("-i","--invites", multiple=True)
@click.option("-l","--lists", "-f" , "lists", multiple=True, type=click.Path(True, file_okay=True, dir_okay=False), help="Reads chosen textfiles with a list of discord invites seperated by lines, The regex built in will sort these out to help you")
@click.option("--proxy","-p", default=None, help="Providing a proxy url will foward discord api requests through the proxy chosen...")
@click.option("--output","-o", default=None, type=click.Path(file_okay=True, dir_okay=False))
@click.option("--threads","-t", default=2, type=click.IntRange(1, clamp=True, max=32), help="The number of threads to run...")
async def cli(proxy:Optional[str] = None,
    invites:list[str] = [],
    threads:int = 2 ,
    output:Optional[str] = None,
    lists:list[str] = []):
    """A Small and simple Asynchronous Discord Invite Scanner 
    Made for small and mass-scale Discord Invite Scanning and Osint
    
    examples if you are confused:

    python disscan.py -i GeometryDash -f invites.txt

    python disscan.py -i discord.gg/invite_1 discord.gg/invite_2

    """
    await Config(proxy, invites, threads, output, lists).run_async()

if __name__ == "__main__":
    banner()
    cli()

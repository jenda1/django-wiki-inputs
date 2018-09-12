from aiostream import core
from .. import stream

@core.operator
async def echo(user, path, args):
    source = stream.args_stream(user, path, args)

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            yield " ".join([str(x) for x in item['args'] if x is not None])

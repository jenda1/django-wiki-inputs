from aiostream import core
import html


@core.operator(pipable=True)
async def html_escape(source, user, path):
    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            s = " ".join([str(x) for x in item if x is not None])
            yield html.escape(s).replace('\n', "<br />")

from aiostream import stream, core
import logging
from .. import stream as my_stream
from .. import misc
import ipdb  # NOQA

logger = logging.getLogger(__name__)

@core.operator
async def get(ic, args):
    if len(args) != 2:
        yield f"⚠ user() requires 2 arguments ⚠"
        return

    if type(args[0]) is not dict or 'path' not in args[0]:
        yield f"⚠ user() first argument must be input ⚠"
        return

    user = ic.user
    while True:
        logger.debug(f"{ic.user}, {args}")
        src = [await my_stream.arg_stream(ic, ic.user, args[1]),
               await my_stream.arg_stream(ic, user, args[0])]
        logger.debug(f"{ic.user}, src:{src}")

        s = stream.ziplatest(*src)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                logger.debug(f"{ic.user}, i:{i}")

                u = ic.user if i[0] is None else await misc.str_to_user(i[0]['val'])
                u = ic.user if u is None else u

                if u != user:
                    user = u
                    break

                yield i[1]

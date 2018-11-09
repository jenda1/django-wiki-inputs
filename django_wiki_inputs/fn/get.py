from aiostream import stream, core
import logging
from channels.db import database_sync_to_async
import re
import pathlib
from .. import stream as my_stream
from .. import models
from .. import misc
import ipdb  # NOQA

logger = logging.getLogger(__name__)


filt_re = re.compile(r"^_(.+)_$")

@database_sync_to_async
def db_get_input_users(article, name, flt):
    q = models.Input.objects.filter(article=article, name=name)

    if flt != 'all':
        q = q.filter(owner__group__name=flt)

    return q.order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')


async def get_users(article, name, items):
    is_list = len(items) > 1
    users = set()

    for x in items:
        if x['type'] == 'str':
            flt = x['val']
        elif x['type'] == 'select':
            flt = x['val']
        else:
            logger.warning(f"??? {x}")
            continue

        m = filt_re.match(flt)
        if m:
            is_list = True

            for u in await db_get_input_users(article, name, m.group(1)):
                if u.owner in users:
                    continue

                if ic.user.pk == article.current_revision.user.pk:
                    users_new.add(u.owner.username)
                    continue
                # FIXME: elif can_read!!!: user_new.add(u
        else:
            u = await misc.db_get_user(flt)
            if u:
                users.add(u.username)

    return users, is_list






@core.operator
async def get(ic, args):
    if len(args) < 2:
        yield {'type': 'error', 'val': "⚠ get() requires at least 2 arguments ⚠"}
        return

    if not isinstance(args[0], pathlib.Path):
        yield {'type': 'error', 'val': "⚠ get() first argument must be input ⚠"}
        return

    field_src = await my_stream.field_src(ic, args[0])
    if field_src is None:
        yield {'type': 'error', 'val': "⚠ get() first argument must be existing input ⚠"}
        return

    users = set()

    while True:
        src = [my_stream.read_field(ic, x, field_src) for x in users]

        src += [await my_stream.arg_stream(ic, ic.user.username, x) for x in args[1:]]

        s = stream.ziplatest(*src, partial=False)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if None in i[len(users):]:
                    continue

                users_new, is_list = await get_users(field_src[0].article, field_src[1], i[len(users):])

                if users != users_new:
                    users = users_new
                    break

                if is_list:
                    yield {'type': 'user-list', 'val': dict(zip(users, i[:len(users)]))}
                else:
                    yield i[0]

            else:
                return

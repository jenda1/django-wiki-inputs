from django.contrib.auth.models import User
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
def db_get_input_users(md, name, items):
    is_list = len(items) > 1
    users = set()
    for flt in items:
        if 'val' not in flt:
            continue

        if isinstance(flt['val'], User):
            users.add(flt['val'])
        else:
            m = filt_re.match(flt['val'])
            if m:
                is_list = True

                qs = models.Input.objects.filter(article=md.article, name=name)
                if flt != 'all':
                    qs = qs.filter(owner__groups__name=m.group(1))
                qs = qs.order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')

                for i in qs.all():
                    users.add(i.owner.username)
            else:
                u = misc.dbsync_get_user(flt['val'])
                if u:
                    users.add(u.username)

    return users, is_list



@core.operator
async def get(ic, args):
    if len(args) < 2:
        yield {'type': 'error', 'val': "⚠ get() requires at least 2 arguments ⚠"}
        return

    if not isinstance(args[0], pathlib.Path):
        yield {'type': 'error', 'val': "⚠ get() first argument must be path ⚠"}
        return


    path = misc.normpath(ic, args[0])
    md = await misc.get_markdown_factory().get_markdown(path.parent, ic.user)
    if md is None:
        yield {'type': 'error', 'val': f"⚠ get() article {path.parent} does not exist ⚠"}
        return

    users = set()

    while True:
        src = [my_stream.read_field(ic, x, path) for x in users]
        src += [await my_stream.arg_stream(ic, ic.user, x) for x in args[1:]]

        s = stream.ziplatest(*src, partial=False)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if None in i[len(users):]:
                    continue

                users_new, is_list = await db_get_input_users(md, path.name, i[len(users):])

                if set([u.pk for u in users]) != set([u.pk for u in users_new]):
                    users = users_new
                    break

                if is_list:
                    yield {'type': 'user-list', 'val': dict(zip([u.username for u in users], i[:len(users)])), }
                else:
                    yield i[0]

            else:
                return

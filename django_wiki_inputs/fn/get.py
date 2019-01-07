from django.db.models import Q
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
def db_get_input_users(md, field, qfilter, items):
    is_list = len(items) > 1

    qall = None
    for flt in items:
        if 'val' not in flt:
            continue

        if isinstance(flt['val'], User):
            q = Q(owner=flt['val'])

        else:
            m = filt_re.match(flt['val'])
            if m:
                is_list = True

                if m.group(1) == 'all':
                    q = Q(owner__groups__name__isnull=False)
                else:
                    q = Q(owner__groups__name=m.group(1))

            else:
                q = Q(owner=misc.dbsync_get_user(flt['val']))

        if qall is None:
            qall = q
        else:
            qall |= q

    q = qfilter & qall

    qs = models.Input.objects.filter(qfilter & qall).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')

    return [i.owner for i in qs.all()], is_list


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

    field = md.input_fields.get(path.name)
    if field is None:
        yield {'type': 'error', 'val': f"⚠ get() article {path.name} does not exist ⚠"}

    q = Q(article=md.article) & Q(name=field['name'])
    if field['can_write'] in [False, None]:
        q &= Q(owner=ic.user)

    users = set()

    while True:
        src = [my_stream.read_field(ic, x, path) for x in users]
        src += [await my_stream.arg_stream(ic, ic.user, x) for x in args[1:]]
        if len(users) == 0:
            src += [my_stream.read_field(ic, ic.user, path)]

        s = stream.ziplatest(*src, partial=False)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                users_new, is_list = await db_get_input_users(md, field, q, (i[len(users):])[:len(args[1:])])

                if set([u.pk for u in users]) != set([u.pk for u in users_new]):
                    users = users_new
                    break

                if is_list:
                    yield {'type': 'user-list', 'val': dict(zip([u.username for u in users], i[:len(users)])), }
                else:
                    yield i[0]

            else:
                return

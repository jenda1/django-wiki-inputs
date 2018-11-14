from channels.db import database_sync_to_async
from aiostream import stream, core
import logging
import json
import pathlib
import os

from . import misc
from . import fn
from . import models

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_is_user_in_group(user, grp):
    return user.groups.filter(name=grp.name).exists()



@database_sync_to_async
def db_user_group_exists(user, grp):
    return user.groups.filter(name=grp).exists()


@database_sync_to_async
def db_get_input(article, name, uname, curr_pk, with_history=False):
    req = models.Input.objects.filter(
        article=article,
        owner__username=uname,
        name=name)

    out = list()
    for x in req:
        if curr_pk == x.pk and not out:
            return None

        val = json.loads(x.val)
        val['pk'] = x.pk
        val['created'] = x.created.isoformat(),
        val['author'] = None if x.author is None else x.author.username,

        out.append(val)

        if not with_history:
            break

    return out


async def can_read_usr(md, inp, user):
    if md.article.current_revision.user.pk == user.pk:
        return True

    if 'can_read' not in inp['args']:
        return False

    can_read = inp['args']['can_read']

    if can_read == '_all_':
        return True

    # user is in the can_read group
    if can_read == '_':
        grp = await misc.db_get_group(can_read.strip('_'))
        if grp is None:
            logger.debug(f"{md.article}: {inp['name']}: can_read use unknown group {can_read}")
            return False

        return await db_is_user_in_group(user, grp)

    # or can_read equals to the user
    return can_read == user.username or can_read == user.email


async def field_src(ic, path):
    p = pathlib.Path(os.path.normpath(os.path.join(ic.path, str(path))))

    md = await misc.get_markdown_factory().get_markdown(p.parent, ic.user)
    if md:
        return (md, p.name)

    logger.debug(f"{ic.user}@{path}: article {p.parent} does not exits or user has no read permission")



@core.operator  # NOQA
async def read_field(ic, uname, src, with_history=False):
    if src is None:
        yield None
        return

    md = src[0]
    name = src[1]

    if name in md.source_fields:
        if with_history:
            yield [md.source_fields.get(name)]
        else:
            yield md.source_fields.get(name)
        return

    for field in md.input_fields:
        if field['cmd'] == 'input' and field['name'] == name:
            break
    else:
        yield None
        return

    if ic.user.username != uname and not await can_read_usr(md, field, ic.user):
        yield {'type': 'error', 'val': "🚫"}
        return

    curr_pk = None
    default = {
        'type':field['args']['type'],
        'created': None,
        'author': None,
        'val':field['args'].get('default'),
    }

    while True:
        if field['args'].get('dummy', False):
            yield ic.dummy_val.get(name, default) if ic.md == md else None

        else:
            out = await db_get_input(md.article, name, uname, curr_pk, with_history)
            if out is not None:
                if with_history:
                    yield out
                else:
                    yield out[0] if len(out) else default

                if out:
                    logger.debug(out)
                    curr_pk = out[0]['pk']

        async with field['cv']:
            await field['cv'].wait()


async def arg_stream(ic, uname, arg):
    if type(arg) in [int, str, float]:
        return stream.just({'type': type(arg).__name__, 'val': arg})

    elif isinstance(arg, pathlib.Path):
        return read_field(ic, uname, await field_src(ic, arg))

    elif type(arg) is dict and 'fname' in arg:
        return display_fn(ic, arg)

    else:
        logger.warning(f"{ic.user}@{ic.path}: argument {arg}: unknow type")
        return stream.empty()


#@core.operator
#async def args_stream(ic, args):
#    out = [await arg_stream(ic, ic.user.username, arg) for arg in args]
#
#    s = stream.ziplatest(*out, partial=False)
#    async with core.streamcontext(s) as streamer:
#        async for i in streamer:
#            yield {'args': i}


@core.operator
async def display_fn(ic, field):
    try:
        m = getattr(fn, field['fname'])
        fnc = getattr(m, field['fname'])

        source = fnc(ic, field['args'])
    except AttributeError:
        yield {'type': 'error', 'val': f"⚠ neznámá funkce {field['fname']}"}
        return

    try:
        async with core.streamcontext(source) as streamer:
            async for item in streamer:
                yield item
    finally:
        if field['fname']:
            logger.debug(f"{ic.user}@{ic.path}: finalize function {field['fname']}")
        else:
            logger.debug(f"{ic.user}@{ic.path}: finalize function pprint")


@core.operator
async def display(ic, idx):
    field = ic.md.input_fields[idx]
    if 'fn' in field:
        source = display_fn(ic, {'fname': 'pprint', 'args': [field['fn']]})
    elif 'path' in field:
        source = display_fn(ic, {'fname': 'pprint', 'args': [field['path']]})

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            yield {'type': 'display', 'id': idx, 'val': item}


@core.operator
async def input(ic, idx):
    field = ic.md.input_fields[idx]

    owner = ic.user

    while True:
        src = [await arg_stream(ic, owner.username, pathlib.Path(field['name']))]

        if 'owner' in field['args']:
            src.append(await arg_stream(ic, ic.user.username, pathlib.Path(field['args']['owner'])))

        s = stream.ziplatest(*src, partial=False)
        async with core.streamcontext(s) as streamer:
            async for i in streamer:
                if 'owner' in field['args']:
                    if i[1] is None:
                        continue
                    else:
                        o = await misc.str_to_user(i[1]['val'])
                        o = o if o else ic.user

                    if o != owner:
                        owner = o
                        break

                out = dict(type='input', id=idx, disabled=True)
                out['owner'] = None if ic.user == owner else owner.username
                out['val'] = '' if i[0]['val'] is None else str(i[0]['val'])
                out['disabled'] = ic.md.article.current_revision.locked

                if field['args']['type'] in ['file', 'files', 'select']:
                    out['val'] = None

                if field['args']['type'] != i[0]['type']:
                    logger.warning(f"field type error: {field['args']['type']} != {i[0]['type']}")

                yield out

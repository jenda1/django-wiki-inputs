from channels.db import database_sync_to_async
from aiostream import stream, core
import logging
import json
import pathlib
import os

from . import misc
from . import fn

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_is_user_in_group(user, grp):
    return user.groups.filter(name=grp.name).exists()



@database_sync_to_async
def db_user_group_exists(user, grp):
    return user.groups.filter(name=grp).exists()



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
async def read_field(ic, user, src):
    if src is None:
        yield None
        return

    md = src[0]
    name = src[1]

    if name in md.source_fields:
        yield md.source_fields.get(name)
        return

    for field in md.input_fields:
        if field['cmd'] == 'input' and field['name'] == name:
            break
    else:
        yield None
        return

    if ic.user.pk != user.pk and not await can_read_usr(md, field, ic.user):
        yield {'type': 'error', 'val': "🚫"}
        return

    last_pk = None
    while True:
        default = {'type': field['args']['type'],
                   'val': field['args'].get('default'),
                   'default': True}

        if field['args'].get('dummy', False):
            if ic.md == md:
                yield ic.dummy_val.get(name, default)
        else:
            db_val = await misc.db_get_input(md.article, name, user)
            if db_val is None:
                yield default

            elif last_pk != db_val.pk:
                last_pk = db_val.pk
                yield json.loads(db_val.val)

        async with field['cv']:
            await field['cv'].wait()


async def arg_stream(ic, user, arg):
    if type(arg) in [int, str, float]:
        return stream.just({'type': type(arg).__name__, 'val': arg})

    elif isinstance(arg, pathlib.Path):
        return read_field(ic, user, await field_src(ic, arg))

    elif type(arg) is dict and 'fname' in arg:
        return display_fn(ic, arg)

    else:
        logger.warning(f"{ic.user}@{ic.path}: argument {arg}: unknow type")
        return stream.empty()


@core.operator
async def args_stream(ic, args):
    out = [await arg_stream(ic, ic.user, arg) for arg in args]

    s = stream.ziplatest(*out, partial=False)
    async with core.streamcontext(s) as streamer:
        async for i in streamer:
            yield {'args': i}


@core.operator
async def display_fn(ic, field):
    try:
        m = getattr(fn, field['fname'])
        fnc = getattr(m, field['fname'])

        source = fnc(ic, field['args'])
    except AttributeError:
        logger.warning(f"{ic.user}@{ic.path}: unknown display method {field['fname']}")
        yield "\u26A0"
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
        src = [await arg_stream(ic, owner, pathlib.Path(field['name']))]

        if 'owner' in field['args']:
            src.append(await arg_stream(ic, ic.user, pathlib.Path(field['args']['owner'])))

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

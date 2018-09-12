from django.contrib.auth.models import User, Group
from channels.db import database_sync_to_async
from aiostream import stream, core
import logging
import json

from . import models
from . import misc
from . import fn

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_is_user_in_group(user, grp):
    return user.groups.filter(name=grp.name).exists()



@database_sync_to_async
def db_get_input_grp(article, name, grp):
    if grp is True:
        return models.Input.objects.filter(
            article=article,
            name=name).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')
    else:
        return models.Input.objects.filter(
            article=article,
            owner__group=grp,
            name=name).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')


@database_sync_to_async
def db_user_group_exists(user, grp):
    return user.groups.filter(name=grp).exists()



async def can_read_usr(md, inp, user):
    if md.article.current_revision.user == user:
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



@core.operator  # NOQA
async def read_field(md, name, user, filt):
    for inp in md.input_fields:
        if inp['cmd'] == 'input' and inp['name'] == name:
            break
    else:
        yield md.source_fields.get(name, None)
        return

    if not (filt is None or await can_read_usr(md, inp, user)):
        yield None
        return

    f = user

    if filt and 'usr' in filt:
        f = await misc.db_get_user(filt['usr'])

    elif filt and 'grp' in filt and filt['grp'] == 'all':
        f = True

    elif filt and 'grp' in filt:
        f = await misc.db_get_group(filt['grp'])

    if f is None:
        yield None
        return

    last = None
    while True:
        if isinstance(f, User):
            db_val = await misc.db_get_input(md.article, name, f)
            if db_val is None:
                yield None

            if last is None or last != db_val.pk:
                last = db_val.pk
                yield json.loads(db_val.val)

        elif f is True or isinstance(f, Group):
            db_vals = await db_get_input_grp(md.article, name, f)

            curr = set([x.pk for x in db_vals])
            if last is None or last != curr:
                last = curr
                yield {i.owner.username: json.loads(i.val) for i in db_vals}

        async with inp['cv']:
            await inp['cv'].wait()


@core.operator
async def args_stream(user, path, args):
    out = list()

    for arg in args:
        if type(arg) in [int, str, float]:
            out.append(stream.just(arg))

        elif type(arg) is dict and 'fname' in arg:
            out.append(display_fn(user, path, arg))

        elif type(arg) is dict and 'path' in arg:
            p = (path/arg['path']).resolve()
            md = await misc.markdown_factory.get_markdown(p.parent, user)
            if md is None:
                logger.debug(f"{user}@{path}: article {p.parent} does not exits or user has no read permission")
                out.append(stream.empty())
            else:
                out.append(read_field(md, p.name, user, arg.get('filter')))

        else:
            logger.warning(f"{user}@{path}: argument {arg}: unknow type")
            out.append(stream.empty)

    s = stream.ziplatest(*out)
    async with core.streamcontext(s) as streamer:
        async for i in streamer:
            yield {'args': i}


@core.operator
async def display_fn(user, path, field):
    # args = await args_to_stream(user, path, field['args'])

    if field['fname'] is None:
        source = fn.echo.echo(user, path, field['args'])
    else:
        try:
            m = getattr(fn, field['fname'])
            fnc = getattr(m, field['fname'])

            source = fnc(user, path, field['args'])
        except AttributeError:
            logger.warning(f"{user}@{path}: unknown display method {field['fname']}")
            yield "\u26A0"
            return

    try:
        async with core.streamcontext(source) as streamer:
            async for item in streamer:
                yield item
    finally:
        logger.debug(f"{user}@{path}: finalize function {field['fname']}")


@core.operator
async def display(ic, idx):
    source = display_fn(ic.user, ic.path, ic.md.input_fields[idx]['fn'])

    async with core.streamcontext(source) as streamer:
        async for item in streamer:
            yield {'type': 'display', 'id': idx, 'val': item}


@core.operator
async def input(ic, idx):
    db_val = await misc.db_get_input(ic.md.article, ic.md.input_fields[idx]['name'], ic.user)
    yield dict(type='input',
               id=idx,
               disabled=False,
               val=json.loads(db_val.val) if db_val else None)

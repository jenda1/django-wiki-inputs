import io
import os
import tarfile
import aiodocker
import asyncio
from aiostream import core, stream
from .. import misc
from .. import stream as my_stream
import logging
import json
import aiohttp
import pathlib
import re
import time
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.db import models


import ipdb  # NOQA

logger = logging.getLogger(__name__)

wi_native_re = re.compile(r'^#\s*WI[_-]NATIVE\s*(.*)$')

class MyException(Exception):
    pass


async def send_item(ws, con, aout, item):
    try:
        out = json.dumps(item)
    except TypeError:
        if isinstance(item[1]['val'], models.Model):
            item = (item[0], item[1].copy())
            item[1]['model'] = str(item[1]['val']._meta)
            item[1]['val'] = item[1]['val'].pk

        out = json.dumps(item)

    if aout.get(item[0], None) == out:
        return

    logger.debug(f"{con['id'][:12]}: < {out[:120]}")
    aout[item[0]] = out

    await ws.send_str(out + "\n")


async def get_dockerfile(dapi, from_image, md, path, user):
    obj = io.BytesIO()
    tar = tarfile.TarFile(fileobj=obj, mode="w")
    dst_path = "/wikilt" + str(path)

    dfile = list()
    dfile.append(f"FROM {from_image}")

    dfile.append(f"ENV PATH {dst_path}:$PATH")
    dfile.append(f"ENV WI_HOME {dst_path}")
    dfile.append(f"RUN mkdir -p '{dst_path}'")

    for fn, item in md.source_fields.items():
        if fn == "_Dockerfile_":
            dfile.extend(item['text'].splitlines())
            continue

        fn = fn.replace('"', '_')
        dst = dst_path + "/" + fn

        ti = tarfile.TarInfo(name=f"wi.{fn}")

        content = item['text'].encode('utf-8')

        if 'type' in item and item['type'] in ['python', 'bash', 'shell'] and item['text'].startswith("#!/"):
            ti.mode = 0o777

        dfile.append(f"COPY [\"{ti.name}\", \"{dst}\"]")

        ti.size = len(content)
        tar.addfile(ti, io.BytesIO(content))


    # for child in md.article.get_children(
    #        articles__article__current_revision__deleted=False,
    #        user_can_read=md.user):
    #    if child.path == 'lib':

    logger.debug("\n\t" + "\n\t".join(dfile))

    content = "\n".join(dfile).encode('utf-8')
    ti = tarfile.TarInfo(name="Dockerfile")
    ti.size = len(content)
    tar.addfile(ti, io.BytesIO(content))

    tar.close()
    obj.seek(0)

    return obj


async def get_image(dapi, path, user):  # NOQA
    md = await misc.get_markdown_factory().get_markdown(str(path), user)
    if md is None:
        raise MyException(f"{path} does not exists")

    if str(path) == '/':
        from_image = "jenda1/testovadlo"
        rebuild_required = False
        image_tag = f"wikilt:{md.article.current_revision.pk}"
    else:
        from_image, rebuild_required = await get_image(dapi, path.parent, user)
        ptag = from_image.split(':')[-1]
        image_tag = f"wikilt{path!s}:{ptag}.{md.article.current_revision.pk}"

    if not rebuild_required:
        try:
            await dapi.images.inspect(image_tag)
            logger.debug(f"{path}@{user}: re-use container {image_tag}")
            return image_tag, False
        except aiodocker.exceptions.DockerError as e:
            if e.status != 404:
                raise e

    log = list()

    tar = await get_dockerfile(dapi, from_image, md, path, user)
    logger.info(f"build {image_tag}")

    try:
        for i in await dapi.images.build(fileobj=tar, tag=image_tag, labels={'django.wiki.inputs': '1'}, encoding="identity"):
            if 'stream' in i:
                log.append("\t"+i['stream'].strip())
            if 'error' in i:
                raise MyException(f"Dockerfile: {i['error']}")
    except MyException:
        raise
    except aiodocker.exceptions.DockerError:
        logger.debug(f"{path}@{user}: docker build failed:\n" + "\n".join(log))
        raise
    finally:
        tar.close()

    return image_tag, True


async def get_container(dapi, path, user):
    if not hasattr(get_container, "_lock"):
        get_container._lock = asyncio.Lock()

    async with get_container._lock:
        img, rebuilded = await get_image(dapi, path, user)
        config = {"Image": img,
                  "AttachStdin": True,
                  "AttachStdout": True,
                  "AttachStderr": True,
                  "Tty": False,
                  "OpenStdin": True,
                  "StdinOnce": True,
                  }

        return await dapi.containers.create(config=config)


@core.operator
async def websocket_reader(ws):
    m = ""
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            m = msg.data.rstrip()
        elif msg.type == aiohttp.WSMsgType.BINARY:
            m += msg.data.decode('utf8')
            if not m.endswith('\n'):
                continue
        elif msg.type == aiohttp.WSMsgType.ERROR:
            logger.error(f"container error: {msg.data}")
            break

        for l in m.splitlines():
            yield ('ws', l)


@core.operator
async def stream_enum(n, s):
    async with core.streamcontext(s) as streamer:
        async for i in streamer:
            yield (n, i)



@core.operator  # NOQA
async def docker(ic, args):
    if len(args) < 1:
        yield None
        return

    if not isinstance(args[0], pathlib.Path):
        yield ('err', "⚠ wrong first argument format ⚠")
        return

    docker_path = pathlib.Path(os.path.normpath(ic.path/args[0]))

    dapi = None
    try:
        dapi = aiodocker.Docker()
        con = await get_container(dapi, docker_path, ic.user)
        if con is None:
            return

        logger.info(f"{con['id'][:12]}: created")

        ain = dict()
        aout = dict()
        for n, arg in enumerate(args[1:]):
            ain[n+1] = stream_enum(n+1, await my_stream.arg_stream(ic, ic.user, arg))

        ws = await con.websocket(stdin=True, stdout=True, stderr=True, stream=True)
        await con.start()

        logger.debug(f"{con['id'][:12]}: started")
        
        msgs_n = 0
        msgs_ts = time.time()


        try:
            restart = True
            while restart:
                restart = False

                if ain:
                    s = stream.merge(*list(ain.values()), websocket_reader(ws))
                else:
                    s = stream.merge(websocket_reader(ws))

                    # if input is empty, send empty message to container
                    logger.debug(f"{con['id'][:12]}: < []")
                    await ws.send_str(json.dumps(list())+"\n")

                out = list()
                async with core.streamcontext(s) as streamer:
                    async for item in streamer:
                        if item[0] == 'ws':
                            logger.debug(f"{con['id'][:12]}: > {item[1][:120]}")

                            msgs_n += 1
                            tdiff = time.time() - msgs_ts

                            if tdiff > 20 and msgs_n > 1000 and msgs_n/tdiff > 20:
                                logger.info(f"{con['id'][:12]}: receiving too much messages {msgs_n} in {tdiff}s")
                                yield {'type': 'error', 'val': f"receiving too much messages {msgs_n} in {tdiff}s"}
                                break

                            m = wi_native_re.match(item[1])
                            if m:
                                if m.group(1) == 'clear':
                                    out = list()
                                    yield {'type': None, 'val': ""}

                                elif m.group(1).startswith('progress'):
                                    yield {'type': 'html', 'val': '<div class="progress"><div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" aria-valuenow="50" aria-valuemin="0" aria-valuemax="100" style="width: 50%"></div></div>'}

                                else:
                                    try:
                                        msg = json.loads(m.group(1))
                                        if msg.get('type') in ['getval']:
                                            mid = msg.get('id')
                                            mval = msg.get('val')
                                            muser = msg.get('user')
                                            if muser is None:
                                                muser = ic.user.pk

                                            if mid is None or mval is None:
                                                logger.warning(f"{con['id'][:12]}: getval: broken msg: > {item[1][:120]}")
                                                continue

                                            if mid in ain:
                                                continue

                                            try:
                                                u = User.objects.get(pk=muser)
                                            except User.DoesNotExist:
                                                logger.warning(f"{con['id'][:12]}: getval: unknown user {muser}")
                                                continue

                                            arg = pathlib.Path(mval)
                                            ain[mid] = stream_enum(mid, await my_stream.arg_stream(ic, u, arg))

                                            restart = True
                                            break
                                        elif msg['type'] in ['error']:
                                            yield msg
                                            break
                                        else:
                                            yield msg
                                    except json.JSONDecodeError as e:
                                        logger.warning(f"{con['id'][:12]}: broken msg: {e!s}")
                                        continue

                            else:
                                out.append(item[1])
                                yield {'type': 'stdout', 'val': "\n".join(out)}

                        elif item[0] == 'err':
                            logger.debug(f"{con['id'][:12]}: !! " + ' '.join(str(item[1]).split())[:120])
                            yield {'type': 'error', 'val': item[1]}
                            break

                        else:
                            await send_item(ws, con, aout, item)

        except GeneratorExit:
            pass

        finally:
            logger.debug(f"{con['id'][:12]}: delete")

            try:
                await con.kill()
                await con.delete()
                pass
            except Exception:
                pass

            ws.close()

    except MyException as e:
        yield {'type': 'error', 'val': f"⚠ {e!s} ⚠"}
    except aiodocker.exceptions.DockerError as e:
        yield {'type': 'error', 'val': f"⚠ {e!s} ⚠"}
    except Exception as e:
        logger.exception(e)
        yield {'type': 'error', 'val': f"⚠ {e!s} ⚠"}

    finally:
        if dapi:
            await dapi.close()

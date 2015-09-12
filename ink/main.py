#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import click
import datetime
import django
import json
import os
import mistune
import shutil
from PIL import Image

from django.conf import settings
from django.template import Template, Context
from livereload import Server
from subprocess import call
from yaml import load


BUILD_DIR = ".build"
ROOT_DIR = os.path.abspath(os.getcwd())
INK_DIR = os.path.abspath(os.path.dirname(__file__))
DEV_PORT = "5555"
IGNORE_FILES = [".DS_Store", ".git"]


markdown = mistune.Markdown()



settings.configure(
    TEMPLATE_DIRS=[
        os.path.join(ROOT_DIR, "templates"),
        os.path.join(INK_DIR, "templates"),
        # os.path.join(ROOT_DIR, "pages"),
    ],
    # INSTALLED_APPS=('sorl.thumbnail',),
    # STATIC_ROOT=os.path.join(BUILD_DIR, "static"),
    # MEDIA_ROOT=os.path.join(ROOT_DIR,),
    # THUMBNAIL_DEBUG=True,
    # DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': 'Ink'}},
    # STATIC_URL=static_url,
    # ROOT_URLCONF="",
)
django.setup()


CONFIG = None

# Site config.
if os.path.exists(os.path.join(ROOT_DIR, "site.yml")):
    with open(os.path.join(ROOT_DIR, "site.yml")) as f:
        CONFIG = load(f)

if CONFIG:
    if  "url" not in CONFIG:
        raise AttributeError("Missing url in site")
    SITE_DIR_URL = CONFIG["url"].split("://")[1]

# from sys import path

# PROJECT_ROOT = abspath(join(dirname(__file__), "project"))
# path.insert(0, PROJECT_ROOT)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime) or isinstance(o, datetime.date):
            return o.isoformat()
        if isinstance(o, file):
            return ""

        return json.JSONEncoder.default(self, o)


def date_string_to_datetime(date_string):
    return datetime.datetime.strptime(date_string, "%Y-%m-%d %H:%M")


def generate_thumbs_and_resize(dirpath, filename, out_filename):
    valid_image = False
    try:
        original_image = Image.open(os.path.join(dirpath, filename))
        # do stuff
        valid_image = True
    except IOError:
        # filename not an image file
        pass

    valid_operation = False
    if valid_image:
        renamed_out = out_filename.split(".")
        renamed_out[-2] = "%s-%%s" % renamed_out[-2]
        renamed_out = ".".join(renamed_out)
        orig_width, orig_height = original_image.size

        # make thumbs
        if "width" in CONFIG["images"]["thumbs"]:
            for width in CONFIG["images"]["thumbs"]["width"]:
                thumb_out = renamed_out % ("%sw" % width)
                print(thumb_out)
                im = original_image.copy()
                size = width, orig_height * (float(width) / orig_width)
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumb_out, im.format, quality=100)

        if "height" in CONFIG["images"]["thumbs"]:
            for height in CONFIG["images"]["thumbs"]["height"]:
                thumb_out = renamed_out % ("%sh" % height)
                print(thumb_out)
                im = original_image.copy()
                size = orig_width * (float(height) / orig_height), height
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumb_out, im.format, quality=100)

        # resize source to max.
        if "max" in CONFIG["images"]:
            if "width" in CONFIG["images"]["max"]:
                width = CONFIG["images"]["max"]["width"]
                print("Resizing to %s" % width)
                if orig_width > width:
                    size = width, orig_height * (float(width) / orig_width)
                    print(size)
                    im = original_image.copy()
                    im.thumbnail(size, Image.ANTIALIAS)
                    im.save(out_filename, im.format, quality=100)
                    valid_operation = True

            if "height" in CONFIG["images"]["max"]:
                height = CONFIG["images"]["max"]["height"]
                if orig_height > height:
                    im = original_image.copy()
                    size = orig_width * (float(height) / orig_height), height
                    im.thumbnail(size, Image.ANTIALIAS)
                    im.save(out_filename, im.format, quality=100)
                    valid_operation = True

    return valid_operation


def scaffold_site():
    # create folders, index, base templates, static, etc
    # create firebase.json
    # {
    #   "firebase": "inkandfeet",
    #   "public": ".build",
    #   "ignore": [
    #     "firebase.json",
    #     "**/.*",
    #     "**/node_modules/**"
    #   ]
    # }

    pass


def scaffold_piece(title, url):
    now = datetime.datetime.now()
    out_folder = os.path.join(ROOT_DIR, "posts", url)
    if not os.path.exists(out_folder):
        os.makedirs(out_folder)

    with open(os.path.join(out_folder, "meta.yml"), "wb") as f:
        f.write("""url: test
title: %(title)s
description: All about %(title)s

published_date: %(date)s
updated_date: %(date)s

""" % {
                "title": title,
                "date": now.strftime("%Y-%m-%d %H:%M"),
                })

    with open(os.path.join(out_folder, "social.yml"), "wb") as f:
        f.write("""url: test
start_date: %(date)s
posts:
    - twitter:
        publication_plus_days: 0
        content: First tweet
        time: 07:00
        image: header.jpg
    - twitter:
        publication_plus_days: 3
        content: Second tweet body
        time: 07:00
        image: alt.jpg

    - facebook:
        publication_plus_days: 0
        content: I'm posting some cool stuff.
        time: 07:00
        image: header.jpg
    - facebook:
        publication_plus_days: 3
        content: I found something I never expected here in mexico
        time: 07:00
        image: alt.jpg
""" % {
                "title": title,
                "date": now.strftime("%Y-%m-%d"),
                })

    with open(os.path.join(out_folder, "piece.md"), "wb") as f:
        f.write("# %s\n\n" % title)


def build_dev_site():
    return build_site(dev=True)


def build_site(dev=False, clean=False):
    pages = []
    site_info = {}
    now = datetime.datetime.now()

    if clean and os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    if dev:
        static_url = "http://localhost:%s" % DEV_PORT
    else:
        static_url = CONFIG["url"]
    site_data_url = "/static/site.json"

    site_info["static_url"] = static_url
    site_info["pages"] = []
    site_info["posts"] = []

    # Build pages
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "pages"), topdown=False):
        print(dirpath, dirnames, filenames)
        for filename in filenames:
            if filename.endswith(".html"):
                with open(os.path.join(dirpath, filename)) as source:
                    t = Template(source.read())
                    context_dict = CONFIG["context"].copy()
                    context_dict.update({
                        "dev_mode": dev,
                        "page_name": filename.split(".html")[0],
                        "url": filename.split(".html")[0],
                        "canonical_url": "%s/%s" % (static_url, filename.split(".html")[0]),
                        "updated_date": now,
                        "site_data_url": site_data_url,
                    })

                    c = Context(context_dict)
                    out = t.render(c).encode("utf-8")
                    out_filename = os.path.join(BUILD_DIR, filename)
                    if "index.html" not in filename:
                        out_filename = out_filename.replace(".html", "")
                        pass

                    if not os.path.exists(os.path.dirname(out_filename)):
                        os.makedirs(os.path.dirname(out_filename))

                    with open(out_filename, "wb") as dest:
                        dest.write(out)
                        print("Writing %s" % filename)

                    site_info["pages"].append(context_dict)
                    pages.append(filename)

    print("Copying static files",)
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "static"), topdown=False):
        for filename in filenames:
            if filename not in IGNORE_FILES:
                out_filename = os.path.join(
                    ROOT_DIR,
                    BUILD_DIR,
                    dirpath.replace("%s/static/" % ROOT_DIR, ""),
                    filename
                )

                # print(out_filename)
                if not os.path.exists(os.path.dirname(out_filename)):
                    os.makedirs(os.path.dirname(out_filename))

                # If we're optimizing images..
                optimization_enabled = False
                if "images" in CONFIG and "thumbs" in CONFIG["images"]:
                    for size in CONFIG["images"]["thumbs"]:
                        if "-thumb-%s" % size in filename:
                            optimization_enabled = True
                            break

                valid_operation = False
                valid_image = False
                if optimization_enabled:
                    valid_operation = generate_thumbs_and_resize(dirpath, filename, out_filename)

                if not valid_operation:
                    shutil.copyfile(
                        os.path.join(dirpath, filename),
                        out_filename
                    )

            # print("Copying %s" % out_filename)
            print(".",)

    print("Copying extra files",)
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "extra"), topdown=False):
        for filename in filenames:
            if filename not in IGNORE_FILES:
                print(dirpath)
                print(dirpath.replace("%s/extra/" % ROOT_DIR, ""),)
                out_filename = os.path.join(
                    ROOT_DIR,
                    BUILD_DIR,
                    # dirpath.replace("%s/extra/" % ROOT_DIR, ""),
                    filename
                )
                print(out_filename)

                if not os.path.exists(os.path.dirname(out_filename)):
                    os.makedirs(os.path.dirname(out_filename))

                shutil.copyfile(
                    os.path.join(dirpath, filename),
                    out_filename
                )
            print("Copying %s" % filename)

    print("")
    call(["lesscpy", os.path.join(ROOT_DIR, BUILD_DIR, "less"), "-X", "-o", os.path.join(ROOT_DIR, BUILD_DIR, "css")])

    # Build posts
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):
        for filename in filenames:
            if "piece.md" in filename:
                # Found a folder.

                # Make sure it's got the stuffs.

                if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")):
                    print(("Missing meta.yml"))
                    break
                else:
                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")) as f:
                        meta_config = load(f)
                if "published" in meta_config and meta_config["published"] is not True:
                    print("Not published")
                else:
                    if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")):
                        print(("Missing social.yml"))
                        break
                    else:
                        with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")) as f:
                            social_config = load(f)

                    if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "header.jpg")):
                        print(("Missing header.jpg"))
                        break

                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, filename)) as source:
                        raw_source = source.read().strip()
                        first_line = raw_source.split("\n")[0]
                        if (first_line.replace("#", "").strip() == meta_config["title"]):
                            raw_source = "\n".join(raw_source.split("\n")[1:])

                        # piece_body = markdown(raw_source)
                        if "url" in  meta_config:
                            url = meta_config["url"]
                        else:
                            url = dirpath.split("/")[-1]
                            if "index.html" not in filename:
                                url = url.replace(".html", "")

                        out_filename = os.path.join(BUILD_DIR, url)

                        header_image = meta_config.get("header_image", "header.jpg")
                        social_image = meta_config.get("social_image", header_image)

                        resources_url = "%s/resources/%s" % (
                            static_url,
                            meta_config["url"],
                        )
                        with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, social_image)) as social_file:
                            social_url = "%s/resources/%s/%s" % (
                                static_url,
                                meta_config["url"],
                                social_image,
                            )
                            thumbs = {}
                            renamed_out = social_url.split(".")
                            renamed_out[-2] = "%s-%%s" % renamed_out[-2]
                            renamed_out = ".".join(renamed_out)

                            # make thumbs
                            if "width" in CONFIG["images"]["thumbs"]:
                                for width in CONFIG["images"]["thumbs"]["width"]:
                                    thumb_out = renamed_out % ("%sw" % width)
                                    print(thumb_out)
                                    thumbs["%sw" % width] = thumb_out.replace(resources_url, "")

                            if "height" in CONFIG["images"]["thumbs"]:
                                for height in CONFIG["images"]["thumbs"]["height"]:
                                    thumb_out = renamed_out % ("%sh" % height)
                                    print(thumb_out)
                                    thumbs["%sh" % height] = thumb_out.replace(resources_url, "")

                            context_dict = CONFIG["context"].copy()
                            context_dict.update(meta_config)
                            context_dict.update({
                                "dev_mode": dev,
                                "social_url": social_url,
                                "social_file": social_file,
                                "resources_url": resources_url,
                                "published_date": date_string_to_datetime(meta_config["published_date"]),
                                "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                                # "page_name": filename.split(".html")[0],
                                "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                                "site_data_url": site_data_url,
                            })
                            c = Context(context_dict)
                            raw_source = raw_source.replace(
                                '{%% thumbnail "',
                                '{%% thumbnail "posts/%s/' % meta_config["url"],
                            )
                            raw_source = raw_source.replace(
                                "{%% thumbnail '",
                                "{%% thumbnail 'posts/%s/" % meta_config["url"],
                            )
                            t = Template(raw_source)
                            parsed_source = t.render(c)

                            piece_body = markdown(parsed_source)
                            piece_body = piece_body.replace(u"’", '&rsquo;').replace(u"“", '&ldquo;').replace(u"”", '&rdquo;').replace(u"’", "&rsquo;")
                            context_dict.update({
                                "piece_html": piece_body,
                            })
                            c = Context(context_dict)

                            t = Template("""{% extends "post.html" %}""")
                            out = t.render(c).encode("utf-8")

                            if not os.path.exists(os.path.dirname(out_filename)):
                                os.makedirs(os.path.dirname(out_filename))

                            out_folder = os.path.join(ROOT_DIR, BUILD_DIR, "resources", meta_config["url"])
                            print(out_folder)
                            if not os.path.exists(out_folder):
                                os.makedirs(out_folder)

                            social_outfilename = os.path.join(out_folder, social_image)
                            valid_operation = generate_thumbs_and_resize(
                                dirpath,
                                social_image,
                                social_outfilename
                            )

                            shutil.copyfile(
                                os.path.join(ROOT_DIR, BUILD_DIR, dirpath, social_image),
                                social_outfilename
                            )

                            with open(out_filename, "wb") as dest:
                                dest.write(out)
                                print("Writing %s" % filename)

                            if dev:
                                out_filename = "%s-social" % out_filename
                                t = Template("""{% extends "social.html" %}""")
                                piece_context = context_dict.copy()
                                context_dict = CONFIG["context"].copy()
                                context_dict.update(meta_config)
                                context_dict.update({
                                    "dev_mode": dev,
                                    "social_config": social_config,
                                    "piece_context": piece_context,
                                    "piece_html": piece_body,
                                    "social_url": social_url,
                                    "thumbs": thumbs,
                                    "social_file": social_file,
                                    "resources_url": resources_url,
                                    "published_date": date_string_to_datetime(meta_config["published_date"]),
                                    "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                                    # "page_name": filename.split(".html")[0],
                                    "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                                    "site_data_url": site_data_url,
                                })
                                c = Context(context_dict)
                                out = t.render(c).encode("utf-8")

                                if not os.path.exists(os.path.dirname(out_filename)):
                                    os.makedirs(os.path.dirname(out_filename))

                                with open(out_filename, "wb") as dest:
                                    dest.write(out)
                                    print("Writing %s-social" % filename)

                            pages.append(filename)
                            del context_dict["piece_html"]
                            del context_dict["social_file"]
                            if "piece_context" in context_dict:
                                del context_dict["piece_context"]
                            del context_dict["site_data_url"]
                            if "social_config" in context_dict:
                                del context_dict["social_config"]
                            del context_dict["site_name"]
                            del context_dict["dev_mode"]
                            site_info["posts"].append(context_dict)

    print("Optimizing images...")
    if not dev:
        print(os.path.join(ROOT_DIR, BUILD_DIR))
        call("cd %s;picopt -r *" % os.path.join(ROOT_DIR, BUILD_DIR), shell=True)


    site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "site.json")

    if not os.path.exists(os.path.dirname(site_json_filename)):
        os.makedirs(os.path.dirname(site_json_filename))

    with open(site_json_filename, "wb") as site_json:
        out = u"%s" % json.dumps(site_info, cls=DateTimeEncoder, sort_keys=True)
        site_json.write(out.encode('utf-8'))

    print("build site")


def serve_site():
    server = Server()
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'pages'), build_dev_site)
    server.watch('%s/*' % os.path.join(ROOT_DIR, 'pages'), build_dev_site)
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'posts'), build_dev_site)
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'static'), build_dev_site)
    server.watch('%s/*' % os.path.join(ROOT_DIR, 'templates'), build_dev_site)
    server.watch('%s/*' % os.path.join(INK_DIR, 'templates'), build_dev_site)
    server.serve(root='.build/', open_url_delay=0.5, port=DEV_PORT)


@click.group()
def cli():
    """Ink.  Publication made simple."""
    pass


@cli.command()
def build():
    build_site()


@cli.command()
def write():
    """Start a new piece"""
    click.echo("Fantastic. Let's get started. ")
    title = click.prompt("What's the title?")

    # Make sure that title doesn't exist.
    url = click.prompt("What's the URL?", default=title.replace(" ", "-").lower())

    # Make sure that title doesn't exist.
    click.echo("Got it. Creating %s..." % url)
    scaffold_piece(title, url)


@cli.command()
def scaffold():
    """Start a new site."""
    click.echo("A whole new site? Awesome.")
    title = click.prompt("What's the title?")
    url = click.prompt("Great. What's url? http://")

    # Make sure that title doesn't exist.
    click.echo("Got it. Creating %s..." % url)
    # call(["firebase" "init"])


@cli.command()
def publish():
    """Publish the site"""
    build_site(dev=False)
    click.echo('Deploying the site...')
    # call("firebase deploy", shell=True)
    call("rsync -avz -e ssh --progress %s/ %s" % (BUILD_DIR, CONFIG["scp_target"],), shell=True)


@cli.command()
def list():
    """List all posts"""
    click.echo('List all posts')


@cli.command()
def serve():
    """Serve the site for local testing and editing."""
    build_site(dev=True, clean=True)
    serve_site()


if __name__ == '__main__':
    cli()

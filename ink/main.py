#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import click
import datetime
import django
import json
import os
import mistune
import requests
import shutil
import sys
import time
from PIL import Image

from django.conf import settings
from django.template import Template, Context
from django.utils.text import slugify
from livereload import Server
from subprocess import call
from yaml import load, dump


BUILD_DIR = ".build"
CACHE_DIR = ".cache"
ROOT_DIR = os.path.abspath(os.getcwd())
INK_DIR = os.path.abspath(os.path.dirname(__file__))
DEV_PORT = "5555"
IGNORE_FILES = [".DS_Store", ".git"]
pages = []
site_info = {}
private_site_info = {}
dev = False
static_url = ""
site_data_url = ""
facebook_profiles = []
twitter_profiles = []

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
    if "url" not in CONFIG:
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


def echo(str):
    click.echo(str)


def error(str):
    click.secho(str, fg="red")


def warn(str):
    click.secho(str, fg="yellow")


def generate_thumbs_and_resize(dirpath, filename, out_filename):
    # print("dirpath, filename, out_filename")
    # print(dirpath)
    # print(filename)
    # print(out_filename)
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
                # print(thumb_out)
                im = original_image.copy()
                size = width, orig_height * (float(width) / orig_width)
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumb_out, im.format, quality=85)

        if "height" in CONFIG["images"]["thumbs"]:
            for height in CONFIG["images"]["thumbs"]["height"]:
                thumb_out = renamed_out % ("%sh" % height)
                # print(thumb_out)
                im = original_image.copy()
                size = orig_width * (float(height) / orig_height), height
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumb_out, im.format, quality=85)

        # resize source to max.
        if "max" in CONFIG["images"]:
            if "width" in CONFIG["images"]["max"]:
                width = CONFIG["images"]["max"]["width"]
                # print("Resizing to %s" % width)
                if orig_width > width:
                    size = width, orig_height * (float(width) / orig_width)
                    # print(size)
                    im = original_image.copy()
                    im.thumbnail(size, Image.ANTIALIAS)
                    im.save(out_filename, im.format, quality=85)
                    valid_operation = True

            if "height" in CONFIG["images"]["max"]:
                height = CONFIG["images"]["max"]["height"]
                if orig_height > height:
                    im = original_image.copy()
                    size = orig_width * (float(height) / orig_height), height
                    im.thumbnail(size, Image.ANTIALIAS)
                    im.save(out_filename, im.format, quality=85)
                    valid_operation = True

    return valid_operation


def modification_date(filename):
    t = os.path.getmtime(filename)
    return datetime.datetime.fromtimestamp(t)


def is_newer(dirpath, filename):
    # check against cache.
    cache_dir_path = os.path.join(ROOT_DIR, CACHE_DIR, dirpath.replace("%s/" % ROOT_DIR, ""))
    try:
        cache = modification_date(os.path.join(cache_dir_path, filename))
        actual = modification_date(os.path.join(ROOT_DIR, dirpath, filename))
        return actual > cache
    except OSError:
        return True
    except:
        import traceback
        traceback.print_exc()
        return True


def exists(dirpath, filename):
    return os.path.exists(os.path.join(dirpath, filename))


def cache_file(dirpath, filename):
    cache_dir_path = os.path.join(ROOT_DIR, CACHE_DIR, dirpath.replace("%s/" % ROOT_DIR, ""))
    if not os.path.exists(cache_dir_path):
        os.makedirs(cache_dir_path)

    shutil.copy2(
        os.path.join(ROOT_DIR, dirpath, filename),
        os.path.join(cache_dir_path, filename)
    )


def publish_datetime(social_post, post):
    post_date = post["social"]["start_date"]
    post_time = social_post["time"]
    plus_days = int(social_post["publication_plus_days"])
    pub_date = datetime.datetime.strptime("%s %s" % (post_date, post_time), "%Y-%m-%d %H:%M")
    pub_date = pub_date + datetime.timedelta(days=plus_days)
    return pub_date


def publish_timestamp(social_post, post):
    dt = publish_datetime(social_post, post)
    return int(time.mktime(dt.timetuple()))


def post_in_future(social_post, post):
    now = time.mktime(datetime.datetime.now().timetuple())
    return now < publish_timestamp(social_post, post)


def publish_facebook(social_post, post):
    # print "Facebook %s" % social_post
    url = "/updates/create.json"
    # print(social_post)
    # print(post["meta"])
    # print(post["site"])

    # if post["meta"]["url"] not in social_post["content"]:
    #     text_with_url = "%s %s" % (
    #         social_post["content"],

    #     )
    # else:

    text_with_url = social_post["content"]
    data = []
    for f in facebook_profiles:
        data.append(("profile_ids[]", f["id"]))
    data.append(("text", text_with_url))
    data.append(("scheduled_at", publish_timestamp(social_post, post)))
    data.append(("media[link]", "%s/%s" % (CONFIG["url"], post["meta"]["url"])))
    data.append(("media[description]", post["meta"]["description"]))
    data.append(("media[title]", post["meta"]["title"]))
    data.append(("media[picture]", post["site"]["social_url"]))
    buffer_post(url, data)


def publish_twitter(social_post, post):
    url = "/updates/create.json"

    # if post["meta"]["url"] not in social_post["content"]:
    #     text_with_url = "%s %s" % (
    #         social_post["content"],
    #         "%s/%s" % (CONFIG["url"], post["meta"]["url"])
    #     )
    # else:
    text_with_url = social_post["content"]
    data = []
    for f in twitter_profiles:
        data.append(("profile_ids[]", f["id"]))
    data.append(("text", text_with_url))
    data.append(("scheduled_at", publish_timestamp(social_post, post)))
    data.append(("media[link]", "%s/%s" % (CONFIG["url"], post["meta"]["url"])))
    data.append(("media[description]", post["meta"]["description"]))
    data.append(("media[title]", post["meta"]["title"]))
    data.append(("media[picture]", post["site"]["social_url"]))
    data.append(("media[photo]", post["site"]["social_url"]))
    buffer_post(url, data)


def buffer_get(url):
    if (url[0] == "/"):
        url = url[1:]
    url = "https://api.bufferapp.com/%s" % url
    params = {
        "access_token": os.environ["BUFFER_ACCESS_TOKEN"]
    }
    r = requests.get(url, params=params)
    if not r.status_code == 200:
        error(r.json())
        raise Exception("Error connecting to buffer")
    return r.json()


def buffer_post(url, data={}):
    if (url[0] == "/"):
        url = url[1:]
    url = "https://api.bufferapp.com/1/%s" % url
    params = {
        "access_token": os.environ["BUFFER_ACCESS_TOKEN"]
    }
    r = requests.post(url, params=params, data=data)
    if not r.status_code == 200:
        error("%s" % r.json())
        raise Exception("Error connecting to buffer")
    return r.json()


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
        f.write(u"""url: %(url)s
title: %(title)s
description: %(title)s
# post_template: letter.html
# private: true
# date: 2015-10-11
# letter_subject: The Power of Really, Really Crazy Hair
# page_name: letter
# location: Medellin, Antioquia, Colombia


published_date: %(date)s
updated_date: %(date)s

""" % {
                "url": url,
                "title": title,
                "date": "%s" % now.strftime("%Y-%m-%d %H:%M"),
                })

    with open(os.path.join(out_folder, "social.yml"), "wb") as f:
        f.write("""url: %(url)s
start_date: %(date)s
posts:
    - twitter:
        publication_plus_days: 0
        content: "First tweet"
        time: "07:00"
        image: header.jpg
    - twitter:
        publication_plus_days: 3
        content: "Second tweet body"
        time: "07:00"
        image: alt.jpg

    - facebook:
        publication_plus_days: 0
        content: "I'm posting some cool stuff."
        time: "07:00"
        image: header.jpg
    - facebook:
        publication_plus_days: 3
        content: "I found something I never expected here in mexico"
        time: "07:00"
        image: alt.jpg
""" % {
                "url": url,
                "title": title,
                "date": now.strftime("%Y-%m-%d"),
                })

    with open(os.path.join(out_folder, "piece.md"), "wb") as f:
        f.write("# %s\n\n" % title)


def build_dev_site(*args, **kwargs):
    print("args")
    print(args)
    print("kwargs")
    print(kwargs)
    return build_site(dev_mode=True)


def build_site_context(ignore_cache=True):
    print("building context..")
    global site_info
    global private_site_info
    global pages
    site_info = {
        "pages": [],
        "posts": [],
    }
    private_site_info = {
        "pages": [],
        "posts": [],
    }
    pages = []
    now = datetime.datetime.now()
    print os.path.join(ROOT_DIR, "pages")
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "pages"), topdown=False):
        for filename in filenames:
            print filename
            if filename.endswith(".html"):
                if ignore_cache or is_newer(dirpath, filename):
                    with open(os.path.join(dirpath, filename)) as source:
                        context_dict = CONFIG["context"].copy()
                        page_name = filename.split(".html")[0]
                        if page_name == "index":
                            page_name = ""
                        context_dict.update({
                            "dev_mode": dev,
                            "page_name": filename.split(".html")[0],
                            "url": filename.split(".html")[0],
                            "canonical_url": "%s/%s" % (static_url, page_name),
                            "updated_date": now,
                            "site_data_url": site_data_url,
                        })
                        site_info["pages"].append(context_dict)
                        private_site_info["pages"].append(context_dict)
                        pages.append(filename)

    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):
        for filename in filenames:
            if "piece.md" in filename:
                # Found a folder.
                # Make sure it's got the stuffs.

                if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")):
                    print("  ! Missing meta.yml")
                    break
                else:
                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")) as f:
                        meta_config = load(f)
                if "published" in meta_config and meta_config["published"] is not True:
                    print("Not published")
                else:
                    if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")):
                        print("  ! Missing social.yml")
                        break
                    else:
                        with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")) as f:
                            social_config = load(f)

                    header_image = meta_config.get("header_image", "header.jpg")

                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, filename)) as source:
                        print(" - %s" % meta_config["title"])
                        raw_source = source.read().strip()
                        first_line = raw_source.split("\n")[0]
                        if (first_line.replace("#", "").strip() == meta_config["title"]):
                            raw_source = "\n".join(raw_source.split("\n")[1:])

                        # piece_body = markdown(raw_source)
                        if "url" in meta_config:
                            url = meta_config["url"]
                        else:
                            url = dirpath.split("/")[-1]
                            if "index.html" not in filename:
                                url = url.replace(".html", "")

                        out_filename = os.path.join(BUILD_DIR, url)

                        social_image = meta_config.get("social_image", header_image)

                        resources_url = "%s/resources/%s" % (
                            static_url,
                            # meta_config["url"],
                            dirpath.replace("%s/posts/" % ROOT_DIR, "")
                        )
                        thumbs = {}

                        social_url = "%s/%s" % (resources_url, social_image)

                        context_dict = CONFIG["context"].copy()
                        context_dict.update(meta_config)
                        context_dict.update({
                            "dev_mode": dev,
                            "social_url": social_url,
                            # "social_file": social_file,
                            "thumbs": thumbs,
                            "resources_url": resources_url,
                            "published_date": date_string_to_datetime(meta_config["published_date"]),
                            "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                            # "page_name": filename.split(".html")[0],
                            "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                            "site_data_url": site_data_url,
                        })

                        pages.append(filename)

                        if "piece_context" in context_dict:
                            del context_dict["piece_context"]
                        del context_dict["site_data_url"]
                        if "social_config" in context_dict:
                            del context_dict["social_config"]
                        del context_dict["site_name"]
                        del context_dict["dev_mode"]

                # print (meta_config)
                if "private" not in meta_config or meta_config["private"] is False:
                    # print("Not private")
                    site_info["posts"].append(context_dict)

                private_site_info["posts"].append(context_dict)


    # print ("site_info")
    # print (site_info)

def build_pages(ignore_cache=False):
    global site_info
    print "build_pages"
    # print site_info
    build_site_context(ignore_cache=ignore_cache)
    sys.stdout.write("Building pages...")
    now = datetime.datetime.now()
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "pages"), topdown=False):
        for filename in filenames:
            if filename.endswith(".html"):
                if ignore_cache or is_newer(dirpath, filename):
                    cache_file(dirpath, filename)
                    with open(os.path.join(dirpath, filename)) as source:
                        t = Template(source.read())
                        context_dict = CONFIG["context"].copy()
                        page_name = filename.split(".html")[0]
                        if page_name == "index":
                            page_name = ""
                        context_dict.update({
                            "dev_mode": dev,
                            "page_name": filename.split(".html")[0],
                            "url": filename.split(".html")[0],
                            "canonical_url": "%s/%s" % (static_url, page_name),
                            "updated_date": now,
                            "site_data_url": site_data_url,
                            "site_info": site_info,
                            "private_site_info": private_site_info,
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

                        # site_info["pages"].append(context_dict)
                        # private_site_info["pages"].append(context_dict)
                        # pages.append(filename)
            sys.stdout.write(".")
    sys.stdout.write(" done. \n")


def copy_static_files(ignore_cache=False):
    sys.stdout.write("Copying static files...")
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "static"), topdown=False):
        for filename in filenames:
            if filename not in IGNORE_FILES:
                if ignore_cache or is_newer(dirpath, filename):
                    cache_file(dirpath, filename)
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
                    if "images" in CONFIG and "max" in CONFIG["images"]:
                        optimization_enabled = True
                    if not optimization_enabled:
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
            sys.stdout.write(".")
            sys.stdout.flush()
    print(" done. \n")


def copy_extra_files(ignore_cache=False):
    sys.stdout.write("Copying extra files...")
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "extra"), topdown=False):
        for filename in filenames:
            if filename not in IGNORE_FILES:
                if ignore_cache or is_newer(dirpath, filename):
                    cache_file(dirpath, filename)
                    # print(dirpath)
                    # print(dirpath.replace("%s/extra/" % ROOT_DIR, ""),)
                    out_filename = os.path.join(
                        ROOT_DIR,
                        BUILD_DIR,
                        # dirpath.replace("%s/extra/" % ROOT_DIR, ""),
                        filename
                    )
                    # print(out_filename)

                    if not os.path.exists(os.path.dirname(out_filename)):
                        os.makedirs(os.path.dirname(out_filename))

                    shutil.copyfile(
                        os.path.join(dirpath, filename),
                        out_filename
                    )
                    # print("Copying %s" % filename)
            sys.stdout.write(".")
    sys.stdout.write(" done. \n")


def compile_less(ignore_cache=False):
    print("Compile LESS")
    call(["lesscpy", os.path.join(ROOT_DIR, BUILD_DIR, "less"), "-X", "-f", "-o", os.path.join(ROOT_DIR, BUILD_DIR, "css")])


def build_posts(ignore_cache=False):
    build_site_context(ignore_cache=ignore_cache)
    # Build posts
    sys.stdout.write("Building posts...\n")
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):
        for filename in filenames:
            if "piece.md" in filename:
                # Found a folder.
                # Make sure it's got the stuffs.

                if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")):
                    print("  ! Missing meta.yml")
                    break
                else:
                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "meta.yml")) as f:
                        meta_config = load(f)
                if "published" in meta_config and meta_config["published"] is not True:
                    print("Not published")
                else:
                    if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")):
                        print("  ! Missing social.yml")
                        break
                    else:
                        with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, "social.yml")) as f:
                            social_config = load(f)

                    header_image = meta_config.get("header_image", "header.jpg")
                    no_header = False
                    if not os.path.exists(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, header_image)):
                        print("  ! Missing header.jpg")
                        no_header = True

                    with open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, filename)) as source:
                        print(" - %s" % meta_config["title"])
                        raw_source = source.read().strip()
                        first_line = raw_source.split("\n")[0]
                        if (first_line.replace("#", "").strip() == meta_config["title"]):
                            raw_source = "\n".join(raw_source.split("\n")[1:])

                        # piece_body = markdown(raw_source)
                        if "url" in meta_config:
                            url = meta_config["url"]
                        else:
                            url = dirpath.split("/")[-1]
                            if "index.html" not in filename:
                                url = url.replace(".html", "")

                        out_filename = os.path.join(BUILD_DIR, url)

                        social_image = meta_config.get("social_image", header_image)

                        resources_url = "%s/resources/%s" % (
                            static_url,
                            # meta_config["url"],
                            dirpath.replace("%s/posts/" % ROOT_DIR, "")
                        )
                        thumbs = {}
                        if no_header:
                            social_file = None
                            social_url = ""
                        else:
                            social_file = open(os.path.join(ROOT_DIR, BUILD_DIR, dirpath, social_image))
                            social_url = "%s/%s" % (
                                resources_url,
                                social_image,
                            )
                            renamed_out = social_url.split(".")
                            renamed_out[-2] = "%s-%%s" % renamed_out[-2]
                            renamed_out = ".".join(renamed_out)

                            # make thumbs
                            if "width" in CONFIG["images"]["thumbs"]:
                                for width in CONFIG["images"]["thumbs"]["width"]:
                                    thumb_out = renamed_out % ("%sw" % width)
                                    # print(thumb_out)
                                    thumbs["%sw" % width] = thumb_out.replace(resources_url, "")

                            if "height" in CONFIG["images"]["thumbs"]:
                                for height in CONFIG["images"]["thumbs"]["height"]:
                                    thumb_out = renamed_out % ("%sh" % height)
                                    # print(thumb_out)
                                    thumbs["%sh" % height] = thumb_out.replace(resources_url, "")

                        context_dict = CONFIG["context"].copy()
                        context_dict.update(meta_config)
                        context_dict.update({
                            "dev_mode": dev,
                            "social_url": social_url,
                            "social_file": social_file,
                            "thumbs": thumbs,
                            "resources_url": resources_url,
                            "published_date": date_string_to_datetime(meta_config["published_date"]),
                            "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                            # "page_name": filename.split(".html")[0],
                            "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                            "site_data_url": site_data_url,
                            "site_info": site_info,
                        })
                        if ignore_cache or is_newer(dirpath, filename) or is_newer(dirpath, "meta.yml"):
                            cache_file(dirpath, filename)
                            cache_file(dirpath, "meta.yml")
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
                            piece_body = piece_body.replace(u"’", '&rsquo;').replace(u"“", '&ldquo;').replace(u"”", '&rdquo;').replace(u"’", "&rsquo;");

                            context_dict.update({
                                "piece_html": piece_body,
                            })
                            c = Context(context_dict)

                            t = Template("""{% extends '""" + context_dict["post_template"] + """' %}""")
                            out = t.render(c).encode("utf-8")

                            if not os.path.exists(os.path.dirname(out_filename)):
                                os.makedirs(os.path.dirname(out_filename))

                            # out_folder = os.path.join(ROOT_DIR, BUILD_DIR, "resources", meta_config["url"])
                            out_folder = os.path.join(ROOT_DIR, BUILD_DIR, "resources", dirpath.replace("%s/posts/" % ROOT_DIR, ""))
                            # print(out_folder)
                            if not os.path.exists(out_folder):
                                os.makedirs(out_folder)

                            social_outfilename = os.path.join(out_folder, social_image)
                            valid_operation = generate_thumbs_and_resize(
                                dirpath,
                                social_image,
                                social_outfilename
                            )

                            if not valid_operation and not no_header:
                                shutil.copyfile(
                                    os.path.join(ROOT_DIR, BUILD_DIR, dirpath, social_image),
                                    social_outfilename
                                )

                            with open(out_filename, "wb") as dest:
                                dest.write(out)
                                # print("Writing %s" % filename)

                            # Bundle this in to a base template, as a popup?
                            # if dev:
                            #     out_filename = "%s-social" % out_filename
                            #     t = Template("""{% extends "social.html" %}""")
                            #     piece_context = context_dict.copy()
                            #     context_dict = CONFIG["context"].copy()
                            #     context_dict.update(meta_config)
                            #     context_dict.update({
                            #         "dev_mode": dev,
                            #         "social_config": social_config,
                            #         "piece_context": piece_context,
                            #         "piece_html": piece_body,
                            #         "social_url": social_url,
                            #         "thumbs": thumbs,
                            #         "social_file": social_file,
                            #         "resources_url": resources_url,
                            #         "published_date": date_string_to_datetime(meta_config["published_date"]),
                            #         "updated_date": date_string_to_datetime(meta_config["updated_date"]),
                            #         # "page_name": filename.split(".html")[0],
                            #         "canonical_url": "%s/%s" % (static_url, meta_config["url"]),
                            #         "site_data_url": site_data_url,
                            #     })
                            #     c = Context(context_dict)
                            #     out = t.render(c).encode("utf-8")

                            #     if not os.path.exists(os.path.dirname(out_filename)):
                            #         os.makedirs(os.path.dirname(out_filename))

                            #     with open(out_filename, "wb") as dest:
                            #         dest.write(out)
                            #         print("Writing %s-social" % filename)

                            # pages.append(filename)

                            # del context_dict["piece_html"]
                            # del context_dict["social_file"]
                            # if "piece_context" in context_dict:
                            #     del context_dict["piece_context"]
                            # del context_dict["site_data_url"]
                            # if "social_config" in context_dict:
                            #     del context_dict["social_config"]
                            # del context_dict["site_name"]
                            # del context_dict["dev_mode"]

                if social_file:
                    social_file.close()

                # print (meta_config)
                # if "private" not in meta_config or meta_config["private"] is False:
                #     # print("Not private")
                #     site_info["posts"].append(context_dict)

                # private_site_info["posts"].append(context_dict)


def optimize_images(ignore_cache=False):
    print("Optimizing images...")
    print(os.path.join(ROOT_DIR, BUILD_DIR))
    call("cd %s;picopt -rG *" % os.path.join(ROOT_DIR, BUILD_DIR), shell=True)


def create_sitemap_xml(ignore_cache=False):
    # create sitemaps
    print("Sitemap.xml")
    with open(os.path.join(ROOT_DIR, BUILD_DIR, "sitemap.xml"), "wb") as sitemap:
        context_dict = {
            "info": private_site_info,
        }
        c = Context(context_dict)
        t = Template("""{% extends "sitemap.xml" %}""")
        out = t.render(c)
        sitemap.write(out.encode('utf-8'))


def create_site_jsons(ignore_cache=False):
    site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "site.json")
    private_site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "private.json")

    if not os.path.exists(os.path.dirname(site_json_filename)):
        os.makedirs(os.path.dirname(site_json_filename))

    print("site.jsons")
    with open(site_json_filename, "wb") as site_json:
        out = u"%s" % json.dumps(site_info, cls=DateTimeEncoder, sort_keys=True)
        site_json.write(out.encode('utf-8'))

    with open(private_site_json_filename, "wb") as private_site_json:
        out = u"%s" % json.dumps(private_site_info, cls=DateTimeEncoder, sort_keys=True)
        private_site_json.write(out.encode('utf-8'))


def build_static_files():
    copy_static_files()
    copy_extra_files()
    compile_less()


def build_template_stuff():
    build_pages(ignore_cache=True)
    build_posts(ignore_cache=True)


def build_site(dev_mode=False, clean=False, ignore_cache=None):
    global pages
    global site_info
    global private_site_info
    global dev
    global static_url
    global site_data_url
    dev = dev_mode
    pages = []
    site_info = {}
    private_site_info = {}

    if clean and os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    if not os.path.exists(BUILD_DIR):
        os.makedirs(BUILD_DIR)
    if dev:
        static_url = "http://localhost:%s" % DEV_PORT
    else:
        static_url = CONFIG["url"]

    site_data_url = "/static/site.json"

    site_info["static_url"] = static_url
    # site_info["pages"] = []
    # site_info["posts"] = []
    private_site_info["static_url"] = static_url
    # private_site_info["pages"] = []
    # private_site_info["posts"] = []

    if ignore_cache is None:
        ignore_cache = not dev_mode

    build_pages(ignore_cache=ignore_cache)
    copy_static_files(ignore_cache=ignore_cache)
    copy_extra_files(ignore_cache=ignore_cache)
    compile_less(ignore_cache=ignore_cache)
    build_posts(ignore_cache=ignore_cache)
    if not dev:
        optimize_images(ignore_cache=ignore_cache)
    create_sitemap_xml(ignore_cache=ignore_cache)
    create_site_jsons(ignore_cache=ignore_cache)

    print("Site built.")


def serve_site():
    server = Server()
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'pages'), build_pages)
    server.watch('%s/*' % os.path.join(ROOT_DIR, 'pages'), build_pages)
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'posts'), build_posts)
    server.watch('%s/**/*' % os.path.join(ROOT_DIR, 'static'), build_static_files)
    server.watch('%s/*' % os.path.join(ROOT_DIR, 'templates'), build_template_stuff)
    server.watch('%s/*' % os.path.join(INK_DIR, 'templates'), build_template_stuff)
    server.serve(root='.build/', open_url_delay=0.5, port=DEV_PORT)


@click.group()
def cli():
    """Ink.  Publication made simple."""
    pass


@cli.command()
def build():
    build_site(dev_mode=False)


def do_purge():
    if "CLOUDFLARE_API_KEY" not in os.environ:
        raise Exception("Missing CLOUDFLARE_API_KEY.")
    if "CLOUDFLARE_EMAIL" not in os.environ:
        raise Exception("Missing CLOUDFLARE_EMAIL.")

    api_key = os.environ["CLOUDFLARE_API_KEY"]
    email = os.environ["CLOUDFLARE_EMAIL"]

    # Get the zone from cloudflare
    headers = {
        "X-Auth-Key": api_key,
        "X-Auth-Email": email,
        "Content-Type": "application/json",
    }
    url = "https://api.cloudflare.com/client/v4/zones/"
    params = {
        "name": CONFIG["url"].replace("https://", "").replace("http://", ""),
        "status": "active",
        "page": 1,
        "per_page": 20,
        "order": "status",
        "direction": "desc",
        "match": "all",
    }

    r = requests.get(url, params=params, headers=headers)

    if not r.status_code == 200:
        print("Error at Cloudflare:")
        print(r.json())
        raise Exception("Cache not purged.")

    if "result" in r.json() and len(r.json()["result"]) == 1:
        zone_id = r.json()["result"][0]["id"]
        url = "%s%s/purge_cache" % (url, zone_id)

        data = {
            "purge_everything": True
        }

        r = requests.delete(url, data=json.dumps(data), headers=headers)

        if not r.status_code == 200:
            print(r.status_code)
            print(r.json())
            raise Exception("Error purging cache: %s" % r.json()["errors"][0]["message"])
    else:
        print("Either there isn't a record at cloudflare with domain %s, or there are several." % CONFIG["url"])
        raise Exception("Cache not purged.")
    print("Cache purged.")


@cli.command()
def purge():
    do_purge()


@cli.command()
def write():
    """Start a new piece"""
    click.echo("Fantastic. Let's get started. ")
    title = click.prompt("What's the title?")

    # Make sure that title doesn't exist.
    url = slugify(title)
    url = click.prompt("What's the URL?", default=url)

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
    build_site(dev_mode=False, clean=True)
    click.echo('Deploying the site...')
    # call("firebase deploy", shell=True)
    call("rsync -avz -e ssh --progress %s/ %s" % (BUILD_DIR, CONFIG["scp_target"],), shell=True)
    if "cloudflare" in CONFIG and "purge" in CONFIG["cloudflare"] and CONFIG["cloudflare"]["purge"]:
        do_purge()


@cli.command()
def promote():
    """Schedule all the social media posts."""

    if "BUFFER_ACCESS_TOKEN" not in os.environ:
        warn("Missing BUFFER_ACCESS_TOKEN.")
        echo("To publish to social medial, you'll need an access token for buffer.")
        echo("The simplest way to get one is to create a new app here: https://buffer.com/developers/apps")
        echo("The token you want is the 'Access Token'")
        echo("Once you have it, make it available to ink by putting it in the environment.")

    # GET https://api.bufferapp.com/1/profiles.json
    echo("Verifying available profiles on buffer")
    profiles = buffer_get("/1/profiles.json")
    for p in profiles:
        supported_profile = False
        if p["formatted_service"].lower() == "facebook" or p["formatted_service"].lower() == "facebook page":
            facebook_profiles.append(p)
            supported_profile = True
        elif p["formatted_service"].lower() == "twitter":
            twitter_profiles.append(p)
            supported_profile = True

        if supported_profile:
            click.secho(u"✓  %s: %s" % (p["formatted_service"], p["formatted_username"]), fg="green")

    echo("Checking publication status...")
    site_json_filename = os.path.join(ROOT_DIR, BUILD_DIR, "static", "private.json")
    with open(site_json_filename, "r") as site_json:
        site = load(site_json)

    echo('Reviewing social posts...')

    posts = {}
    unpublished_posts = []

    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT_DIR, "posts"), topdown=False):
        for filename in filenames:
            if "piece.md" in filename:
                if exists(dirpath, "social.yml") and exists(dirpath, "meta.yml"):
                    with open(os.path.join(dirpath, "social.yml")) as f:
                        social = load(f)

                    with open(os.path.join(dirpath, "meta.yml")) as f:
                        meta = load(f)

                    if "url" in meta:
                        site_json_entry = None
                        for sp in site["posts"]:
                            if meta["url"] == sp["url"]:
                                site_json_entry = sp
                                break

                        posts[meta["url"]] = {
                            "meta": meta,
                            "social": social,
                            "dirpath": dirpath,
                            "site": site_json_entry,
                        }
                        if "published" not in social or social["published"] is not True:
                            unpublished_posts.append(meta["url"])
                    else:
                        warn("No url found for %s" % dirpath.replace(ROOT_DIR))

    automark_set = False
    automark = None
    for u in unpublished_posts:
        post = posts[u]

        if "posts" in post["social"] and post["social"]["posts"] and len(post["social"]["posts"]) > 0:
            facebook_posts = []
            twitter_posts = []
            mark_as_published = False

            has_valid_post = False
            for p in post["social"]["posts"]:
                try:
                    if len(p.keys()) != 1:
                        error("Something's formatted wrong in %s's social.yml" % u)
                        break
                    if p.keys()[0] == "facebook":
                        facebook_posts.append(p["facebook"])
                        if post_in_future(p["facebook"], post):
                            has_valid_post = True
                    elif p.keys()[0] == "twitter":
                        if post_in_future(p["twitter"], post):
                            has_valid_post = True
                        twitter_posts.append(p["twitter"])
                    else:
                        warn("Unknown post type: %s.  Skipping." % p.keys()[0])
                except:
                    error("Error parsing social.yml for \"%s\"" % post["meta"]["title"])
                    import traceback
                    traceback.print_exc()

            if not has_valid_post:
                if automark:
                    mark_as_published = True
                else:
                    warn('"%s" hasn\'t been published, but all posts are in the past.' % post["meta"]["title"])
                    if click.confirm("Mark as published?"):
                        mark_as_published = True
                        if not automark_set:
                            if click.confirm("Mark all other similar posts as published?"):
                                automark = True
                            automark_set = True
            else:
                echo('\n"%s" hasn\'t been published to social media.' % post["meta"]["title"])
                if len(facebook_posts) > 0:
                    echo("  Facebook:")
                    for p in facebook_posts:
                        if (len(p["content"]) > 40):
                            truncated_content = "%s..." % p["content"][:40]
                        else:
                            truncated_content = p["content"]
                        if post_in_future(p, post):
                            echo("   - %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))
                        else:
                            warn("   - %s:  \"%s\" skipping (past)" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))
                echo("  Twitter:")
                if len(twitter_posts) > 0:
                    for p in twitter_posts:
                        if (len(p["content"]) > 40):
                            truncated_content = "%s..." % p["content"][:40]
                        else:
                            truncated_content = p["content"]
                        if post_in_future(p, post):
                            echo("   - %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))
                        else:
                            warn("   - %s:  \"%s\" skipping (past)" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ))

                if click.confirm(click.style("  Publish now?", fg="green")):
                    mark_as_published = True
                    echo("  Publishing...")
                    for p in facebook_posts:
                        if post_in_future(p, post):
                            publish_facebook(p, post)
                            if (len(p["content"]) > 40):
                                truncated_content = "%s..." % p["content"][:40]
                            else:
                                truncated_content = p["content"]
                            click.secho(u"   ✓ Twitter %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ), fg="green")
                    for p in twitter_posts:
                        if post_in_future(p, post):
                            publish_twitter(p, post)
                            if (len(p["content"]) > 40):
                                truncated_content = "%s..." % p["content"][:40]
                            else:
                                truncated_content = p["content"]
                            click.secho(u"   ✓ Facebook %s:  \"%s\"" % (
                                publish_datetime(p, post).strftime("%c"),
                                truncated_content,
                            ), fg="green")

                    echo("  Published.")

            # Save as published.
            if mark_as_published or automark:
                post["social"]["published"] = True
                with open(os.path.join(post["dirpath"], "social.yml"), "w") as f:
                    dump(post["social"], f, default_flow_style=False, width=1000)

    if click.confirm("Publish your entire backlog to buffer?"):
        print ("dope")


@cli.command()
def list():
    """List all posts"""
    click.echo('List all posts')


@cli.command()
def serve():
    """Serve the site for local testing and editing."""
    build_site(dev_mode=True)
    serve_site()


if __name__ == '__main__':
    cli()

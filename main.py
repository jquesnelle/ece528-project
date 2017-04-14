from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from google.cloud import datastore, storage
import PIL
from PIL import Image
import hashlib, time, base58, io, types

app = Flask(__name__)
app.config['DEBUG'] = True
gds = datastore.Client('ece528-project')
gcs = storage.Client()
bucket = gcs.get_bucket('ece528-project.appspot.com')


def new_key(filename):
    sha256 = hashlib.sha256()
    sha256.update(str(time.time()) + filename)
    return base58.b58encode(sha256.digest())[:6]


def store_image(key, data, image_format):
    print('Store image ' + key + ' of type ' + image_format)
    filename = key + '.' + image_format
    blob = bucket.blob(filename)
    data.seek(0)
    blob.upload_from_string(data.read(), content_type='image/' + image_format)
    return blob.public_url


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/about')
def about():
    return render_template('about.html')


def pil_fileno_hack(self):
    """
        GAE is stuck at PIL 1.1.7 (it's a special whitelisted lib since usually we can't do native stuff)
        This patches the bug explained here (which happens when we call save): 
            http://stackoverflow.com/questions/33285330/unsupportedoperation-fileno-how-to-fix-this-python-dependency-mess
    """
    raise AttributeError


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('No file uploaded')
        return redirect(request.url)
    file = request.files['file']
    key = new_key(file.filename)
    image = Image.open(file.stream)
    data = io.BytesIO()
    data.fileno = types.MethodType(pil_fileno_hack, data)
    image.save(data, image.format)
    image_format = image.format.lower()
    public_url = store_image(key, data, image_format)
    entity = datastore.Entity(key=gds.key('upload', key))
    entity.update({'original': unicode(image_format), image_format: unicode(public_url), 'views': 0})
    gds.put(entity)
    return jsonify({'key': key})


@app.route('/<string:key>')
def display(key):
    entity = gds.get(gds.key('upload', key))
    if entity is None:
        return redirect(url_for('index'))
    entity['views'] = entity['views'] + 1
    gds.put(entity)
    return render_template('display.html', key=key, url=entity[entity['original']], views=entity['views'])


def convert_image(key, image_format):
    entity = gds.get(gds.key('upload', key))
    if entity is None:
        return None
    if image_format in entity:
        return entity[image_format]
    original_format = entity['original']
    blob = bucket.blob(key + '.' + original_format)
    data = io.BytesIO()
    blob.download_to_file(data)
    data.seek(0)
    image = Image.open(data)
    if (original_format == 'png' or original_format == 'gif') and (image_format != 'gif' and image_format != 'png'):
        image.load()
        r, g, b, a = image.split()
        image = Image.merge("RGB", (r, g, b))
    data = io.BytesIO()
    data.fileno = types.MethodType(pil_fileno_hack, data)
    image.save(data, image_format)
    public_url = store_image(key, data, image_format)
    entity[image_format] = unicode(public_url)
    gds.put(entity)
    return public_url


@app.route('/<string:key>/download/<string:image_format>')
def download(key, image_format):
    url = convert_image(key, image_format)
    return redirect(url) if url is not None else redirect('/' + key)


@app.route('/<string:key>/download')
def download_original(key):
    entity = gds.get(gds.key('upload', key))
    if entity is None:
        return redirect('/' + key)
    return download(key, entity['original'])


@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, nothing at this URL.', 404

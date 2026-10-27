import hmac
import logging
import os
import time
from html import escape

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, abort, g, request, render_template

application = Flask(__name__)
application.logger.setLevel(logging.INFO)

@application.before_request
def start_request():
    g.started_at = time.perf_counter()

    #CloudFront supplies this header to the origin
    #Health checks need an endpoint that does not require the header.
    secret = os.environ.get("ORIGIN_SECRET","")
    if secret and request.path != "/health":
        supplied = request.headers.get("X-Origin-Verify","")

        if not hmac.compare_digest(supplied, secret):
            abort(403)

@application.after_request
def record_request(response):
    elapsed_ms = (time.perf_counter() - g.started_at) * 1000

    #Do not log credentials, tokens, request bodies, or query strings
    application.logger.info("method=%s path=%s duration_ms=%.1f", request.method, request.path, response.status_code, elapsed_ms)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response

@application.get("/")
def home():
    return render_template("home.html")



@application.get("/health")
def health():
    return {"status": "healthy"}, 200



@application.get("/materials")
def materials():
    # boto3 obtains temporary credentials from the EC2 instance role.
    # No access keys are embedded in the application.
    bucket = os.environ.get("COURSE_BUCKET", "")
    if not bucket:
        return {"error": "Course bucket is not configured."}, 503
    try:
        s3 = boto3.client("s3")
        result = s3.list_objects_v2(
            Bucket=bucket, Prefix="courses/", MaxKeys=20
        )
        items = result.get("Contents", [])
        names = [item["Key"] for item in items
                 if not item["Key"].endswith("/")]
        listing = "".join(f"<li>{escape(name)}</li>" for name in names)
        return ("<h1>Sample material filenames</h1><ul>"
                + (listing or "<li>No sample files found.</li>")
                + "</ul><p><a href='/'>Back</a></p>")
    except (BotoCoreError, ClientError):
        application.logger.exception("Unable to list sample materials")
        return {"error": "Unable to retrieve sample materials."}, 503

def require_demo_test():
    # Test endpoints work only when explicitly enabled with a token.
    enabled = os.environ.get("DEMO_TESTS_ENABLED", "false").lower()
    expected = os.environ.get("DEMO_TEST_TOKEN", "")
    supplied = request.headers.get("X-Demo-Test", "")
    if enabled != "true" or not expected:
        abort(404)
    if not hmac.compare_digest(expected, supplied):
        abort(403)


@application.get("/demo/slow")
def slow():
    require_demo_test()
    time.sleep(3)
    return {"message": "Controlled slow-response test"}


@application.get("/demo/error")
def error():
    require_demo_test()
    return {"error": "Controlled server-error test"}, 500


if __name__ == "__main__":
    application.run(host="127.0.0.1", port=5000, debug=False)
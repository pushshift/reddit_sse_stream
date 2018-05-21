#!/usr/bin/env python3

from flask import Response, Flask, request
from time import sleep
import redis,hiredis
import operator
import ujson as json
import time
import math
from collections import defaultdict

app = Flask(__name__)

@app.route("/test")
def test():
    page = '''
<!doctype html>

<html lang="en">
<head>
  <meta charset="utf-8">
</head>

<body>
<script>
  var source = new EventSource('/stream');
  source.onmessage = function(event){
    alert(event.data);
  };
</script>
</body>
</html>
'''
    return page


@app.route("/")
def stream():

    if 'HTTP_X_FORWARDED_FOR' in request.environ:
        REMOTE_IP = request.environ['HTTP_X_FORWARDED_FOR':
    params = {}
    params['type'] = request.args.get('type')
    params['subreddit'] = request.args.get('subreddit')
    params['author'] = request.args.get('author')

    # Process Parameters by lowercasing all parameter and creating arrays for all parameters except 'type'
    for key in params:
        if params[key] is not None:
            params[key] = params[key].lower()
            if key != 'type':
                params[key] = set(params[key].split(","))

    def eventStream():

        # Establish Redis connection for each connection (Not sure if one Redis connection is green thread safe)
        local = redis.StrictRedis(host='localhost', port=6379, db=1,decode_responses=True)

        # Prepare Redis Pipeline
        pipe = local.pipeline()

        # Find out what the max comment id and max submission id are
        pipe.get('rc:max_id')
        pipe.get('rs:max_id')

        # How much backfill to send on new connections
        COMMENT_HISTORY_AMOUNT = 2500
        SUBMISSION_HISTORY_AMOUNT = 500

        rc_max_id,rs_max_id = pipe.execute()
        rc_max_id = int(rc_max_id) - COMMENT_HISTORY_AMOUNT
        rs_max_id = int(rs_max_id) - SUBMISSION_HISTORY_AMOUNT

        # How many new comments and submissions should we ask for each time?
        com_buffer_size = 25
        sub_buffer_size = 5

        # How many times on average should we query Redis each second?
        # (Note, the multiple of the request size and how often we check should be larger than max Reddit Traffic ...
        # ... in this case, 100 comments per second and 20 submissions per second should be plenty.  We should probably
        # check if there are no Nones returned from Redis and immediately make another request.  If we ask for 25 new comment
        # ids and we get a valid comment for all ids requested, there is likely more data waiting.
        # Calls per second to Redis
        CPS = 5

        # last_sent tells the time a message was last sent -- needed for keepalive
        last_sent = int(time.time())

        # Starting id for keepalive events
        keep_alive_id = 0

        # How often to send keepalives in seconds if no other data is sent?
        KEEP_ALIVE_INTERVAL = 30

        total_comments_sent = 0
        total_submissions_sent = 0
        total_bytes_sent = 0

        while True:

            begin_time = time.time()
            comments_were_full = True
            submissions_were_full = True
            # Do we need to send a keep alive signal?
            if int(time.time()) > last_sent + KEEP_ALIVE_INTERVAL:
                keep_alive_id += 1
                output = "id: {}\nevent: {}\ndata: {}\n\n".format(keep_alive_id,'keepalive','{"tcs":' + str(total_comments_sent) + ',"tss":' + str(total_submissions_sent) + ',"tbs":' + str(total_bytes_sent) + '}')
                total_bytes_sent += len(output)
                yield output
                last_sent = int(time.time())
            feed = []  # Feed will store everything we eventually want to send to the client
            com_ids = [x for x in range(rc_max_id+1,rc_max_id+com_buffer_size+1)]
            sub_ids = [x for x in range(rs_max_id+1,rs_max_id+sub_buffer_size+1)]
            for id in com_ids: pipe.hgetall('rc:id:' + str(id))
            for id in sub_ids: pipe.hgetall('rs:id:' + str(id))
            data = pipe.execute()
            comments = data[:com_buffer_size]
            submissions = data[-sub_buffer_size:]

            for i, comment in enumerate(comments):
                if comment:
                    if params['author'] is None and params['subreddit'] is None:
                        whitelisted = True
                    else:
                        whitelisted = False

                    id = com_ids[i]
                    if id > rc_max_id: rc_max_id = id
                    event = "rc"
                    data = comment['json']
                    created_utc = comment['created_utc']
                    author = comment['author']
                    subreddit = comment['subreddit']

                    if params['author'] is not None:
                        if author in params['author']:
                            whitelisted = True

                    if params['subreddit'] is not None:
                        if subreddit in params['subreddit']:
                            whitelisted = True

                    if not whitelisted: continue

                    total_comments_sent += 1
                    if params['type'] is None or params['type'].startswith('comment') or params['type'] == 'rc':
                        feed.append((id,event,data,created_utc))
                else:
                    comments_were_full = False

            for i, submission in enumerate(submissions):
                if submission:
                    if params['author'] is None and params['subreddit'] is None:
                        whitelisted = True
                    else:
                        whitelisted = False
                    id = sub_ids[i]
                    if id > rs_max_id: rs_max_id = id
                    event = "rs"
                    data = submission['json']
                    created_utc = submission['created_utc']
                    author = submission['author']
                    subreddit = submission['subreddit']

                    if params['author'] is not None:
                        if author in params['author']:
                            whitelisted = True

                    if params['subreddit'] is not None:
                        if subreddit in params['subreddit']:
                            whitelisted = True

                    if not whitelisted: continue

                    total_submissions_sent += 1
                    if params['type'] is None or params['type'].startswith('submission') or params['type'] == 'rs':
                        feed.append((id,event,data,created_utc))
                else:
                    submissions_were_full = False

            if feed:
                s = sorted(feed,key=lambda x: x[3])
                for item in s:
                    output = "id: {}\nevent: {}\ndata: {}\n\n".format(item[0],item[1],item[2])
                    total_bytes_sent += len(output)
                    yield output

            total_loop_time = time.time() - begin_time
            wait = 1 / CPS - total_loop_time
            if wait < 0: wait = 0

            if submissions_were_full or comments_were_full:
                sleep(.025)
            else:
                sleep(wait)

    return Response(eventStream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host='0.0.0.0')

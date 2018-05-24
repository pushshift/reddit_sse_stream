#!/usr/bin/env python3

from flask import Response, Flask, request
import redis,hiredis
import operator
import time
import ujson as json

app = Flask(__name__)

def isInt(astring):
    """ Is the given string an integer? """
    try: int(astring)
    except ValueError: return 0
    else: return 1

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
        REMOTE_IP = request.environ['HTTP_X_FORWARDED_FOR']

    params = dict(request.args)

    # Some error checking
    if 'comment_backfill' in params and 'comment_start_id' in params:
        return json.dumps({'error':'cannot use comment_backfill parameter and comment_start_id parameter at the same time'}), 400, {'ContentType':'application/json'}

    if 'submission_backfill' in params and 'submission_start_id' in params:
        return json.dumps({'error':'cannot use submission_backfill parameter and submission_start_id parameter at the same time'}), 400, {'ContentType':'application/json'}

    # Process type parameter if present
    if 'type' in params:
        params['type'] = params['type'][0]

    # Handle comment_backfill and submission_backfill Parameters
    for key in ['comment_backfill','submission_backfill']:
        if key in params:
            params[key] = params[key][0]
            if isInt(params[key]):
                params[key] = int(params[key])
                if params[key] > 100000: params[key] = 100000
            else:
                return json.dumps({'error':'comment_backfill and/or submission_backfill parameters should be an integer value'}), 400, {'ContentType':'application/json'}
        else:
            params[key] = 0

    # Handle comment_start_id and submission_start_id Parameters if present
    for key in ['comment_start_id','submission_start_id']:
        if key in params:
            params[key] = params[key][0]
            if isInt(params[key]):
                params[key] = int(params[key])
            else:
                return json.dumps({'error':'comment_start_id and/or submission_start_id parameters should be an integer value'}), 400, {'ContentType':'application/json'}

    def eventStream():

        # Establish Redis connection for each connection (Not sure if one Redis connection is green thread safe)
        local = redis.StrictRedis(host='localhost', port=6379, db=1,decode_responses=True)

        # Prepare Redis Pipeline
        pipe = local.pipeline()

        # Find out what the max comment id and max submission id are
        pipe.get('rc:max_id')
        pipe.get('rs:max_id')

        # How much backfill to send on new connections
        COMMENT_HISTORY_AMOUNT = params['comment_backfill']
        SUBMISSION_HISTORY_AMOUNT = params['submission_backfill']

        rc_max_id,rs_max_id = pipe.execute()
        rc_max_id = int(rc_max_id) - COMMENT_HISTORY_AMOUNT
        rs_max_id = int(rs_max_id) - SUBMISSION_HISTORY_AMOUNT

        # How many new comments and submissions should we ask for each time?
        COM_BUFFER_SIZE = 25
        SUB_BUFFER_SIZE = 10

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

        # comment_start_id and submission_start_id take precedence over any other backfill or epoch start settings
        if 'comment_start_id' in params:
            rc_max_id = params['comment_start_id'] - 1
        if 'submission_start_id' in params:
            rs_max_id = params['submission_start_id'] - 1

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
            com_ids = [x for x in range(rc_max_id+1,rc_max_id + COM_BUFFER_SIZE + 1)]
            sub_ids = [x for x in range(rs_max_id+1,rs_max_id + SUB_BUFFER_SIZE + 1)]
            for id in com_ids: pipe.hgetall('rc:id:' + str(id))
            for id in sub_ids: pipe.hgetall('rs:id:' + str(id))
            data = pipe.execute()
            comments = data[:COM_BUFFER_SIZE]
            submissions = data[-SUB_BUFFER_SIZE:]

            for i, comment in enumerate(comments):
                if comment:
                    if 'author' not in params and 'subreddit' not in params:
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

                    if 'author' in params:
                        if author in params['author']:
                            whitelisted = True

                    if 'subreddit' in params:
                        if subreddit in params['subreddit']:
                            whitelisted = True

                    if not whitelisted: continue

                    total_comments_sent += 1
                    if 'type' not in params or params['type'].startswith('comment') or params['type'] == 'rc':
                        feed.append((id,event,data,created_utc))
                else:
                    comments_were_full = False

            for i, submission in enumerate(submissions):
                if submission:
                    if 'author' not in params and 'subreddit' not in params:
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
                    over_18 = submission['over_18']
                    is_self = submission['is_self']

                    if 'over_18' in params:
                        if params['over_18'][0].lower() != over_18.lower(): continue

                    if 'is_self' in params:
                        if params['is_self'][0].lower() != is_self.lower(): continue

                    if 'author' in params:
                        if author in params['author']:
                            whitelisted = True

                    if 'subreddit' in params:
                        if subreddit in params['subreddit']:
                            whitelisted = True

                    if not whitelisted: continue

                    total_submissions_sent += 1
                    if 'type' not in params or params['type'].startswith('submission') or params['type'] == 'rs':
                        feed.append((id,event,data,created_utc))
                else:
                    submissions_were_full = False

            if feed:
                s = sorted(feed,key=lambda x: x[3])
                for item in s:
                    data = item[2]

                    # Is the filter parameter present?  If so, let's only return the fields specified
                    if 'filter' in params:
                        filtered_keys = params['filter'][0].split(',')
                        j = json.loads(item[2])
                        data = json.dumps({k:v for k,v in j.items() if k in filtered_keys})

                    output = "id: {}\nevent: {}\ndata: {}\n\n".format(item[0],item[1],data)
                    total_bytes_sent += len(output)
                    yield output

            total_loop_time = time.time() - begin_time
            wait = 1 / CPS - total_loop_time
            if wait < 0: wait = 0

            if submissions_were_full or comments_were_full:
                time.sleep(.025)
            else:
                time.sleep(wait)

    return Response(eventStream(), mimetype="text/event-stream")

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=5000)

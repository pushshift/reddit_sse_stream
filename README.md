# Reddit SSE Stream

### Link: http://stream.pushshift.io/

## What is this?

This is an SSE stream that you can connect to using a browser or other programs to get a live feed of near real-time Reddit data (couple seconds delayed).

There is a caveat however -- SSE streams currently only work via http (no SSL). However, it does support compression! I highly encourage you to connect using compression headers to conserve bandwidth if you use the full feed.

    curl --verbose --compressed 'http://stream.pushshift.io/?type=comments'

## Parameters Supported

| Parameter        | Description           | Possible Values  |
| ------------- |:-------------| -----:|
| type        |  Restrict feed to a particular event type.  Leave out to receive all event types. | comments,submissions |
| author      | Restrict to certain authors.  Separate multiple authors with a comma.      |   String |
| domain      | Restrict submissions to a domain or group of domains (Comma-delimited)       |   String |
| subreddit   | Restrict to certain subreddits.  Separate multiple subreddits with a comma.       |    String |
| submission_backfill | Starts stream X submissions ago (up to 25,000 submissions) | INT (1-100000)|
| comment_backfill | Starts stream X comments ago (up to 100,000 submissions) | INT (1-100000) |
| submission_start_id | Starts stream at specific submission ID (Used for continuation if the stream is broken | INT |
| comment_start_id | Starts stream at specific comment ID (Used for continuation if the stream is broken) | INT |
| over_18 | Restrict submissions in stream to NSFW or SFW content | Boolean (true or false) |
| is_self | Restrict submissions in stream to self posts or linked posts | Boolean (true or false) |
| filter  | Restrict the returned JSON object to specific keys (comma-delimited for multiple values) | String |

## Examples:

Get only submissions from news and politics:

    curl --verbose --compressed 'http://stream.pushshift.io/?type=submissions&subreddit=politics,news'
Get only comments from automoderator:

    curl --verbose --compressed 'http://stream.pushshift.io/?type=comments&author=automoderator'

Notice: When connecting with compression. It generally takes a little bit of time before it gets started.  Also, only one connection per IP is supported.  If you need additional streams, please contact me.

## Event Types:

| Event        | Description | Currently Implemented |
| ------------- |:-------------|:------------|
| rc | A new Reddit comment in json format | Yes|
| rs | A new Reddit submission in json format | Yes |
| rr | A new Reddit subreddit in json format| No |
| keepalive | A keepalive message (every 30 seconds)| Yes|

## Keepalive Messages:

Currently, a keepalive event is sent to the client every 30 seconds regardless if previous data was sent.  The keepalive event has the following information:

| Key        | Value Description |
| ------------- |:-------------|
| tcs | Total Comments Sent
| tss | Total Submissions Sent |
| tbs | Total bytes sent (uncompressed)|

## Python Consumer Example

pip install sseclient (From this wonderful github: https://github.com/btubbs/sseclient)

Take a look at the consumer_example.py file that shows how to interact with the stream using Python and sseclient.



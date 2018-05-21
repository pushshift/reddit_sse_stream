#!/usr/bin/env python3

from sseclient import SSEClient
import ujson as json

def process_message(msg):
    data = msg.data
    event = msg.event
    id = msg.id
    # do something with data ...
    print(json.loads(data))

messages = SSEClient('http://stream.pushshift.io')
for msg in messages:
    process_message(msg)


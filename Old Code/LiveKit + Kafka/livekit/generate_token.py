"""
[ START ]
    |
    v
+------------------------------+
| <AccessToken> -> __init__()  |
| * init with credentials      |
+------------------------------+
    |
    v
+------------------------------+
| <VideoGrants> -> __init__()  |
| * define permissions         |
+------------------------------+
    |
    v
+------------------------------+
| to_jwt()                     |
| * sign and encode token      |
+------------------------------+
    |
    v
[ END ]
"""
from livekit.api import AccessToken, VideoGrants
import datetime

api_key = "devkey"
api_secret = "devsecret"

token = AccessToken(api_key, api_secret)

token.identity = "test-user"
token.name = "Test User"

token.ttl = datetime.timedelta(hours=10)   # long expiry

token.grants = VideoGrants(
    room_join=True,
    room="test-room",
    can_publish=True,
    can_subscribe=True
)

print(token.to_jwt())
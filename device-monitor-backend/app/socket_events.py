import socketio

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


@sio.event
async def connect(sid, environ, auth=None):
    print(f"[device-monitor socket] connect: {sid}")


@sio.event
async def disconnect(sid):
    print(f"[device-monitor socket] disconnect: {sid}")

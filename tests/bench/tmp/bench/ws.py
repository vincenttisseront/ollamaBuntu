import asyncio, ssl, websockets, json, sys
sys.path.insert(0, "/tmp/bench")
async def echo(ws):
    async for m in ws: await ws.send("écho:" + m)
async def main():
    srv = await websockets.serve(echo, "127.0.0.1", 3000)       # faux Open WebUI (WebSocket)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    async with websockets.connect("wss://127.0.0.1:18843/ws/socket.io/", ssl=ctx) as ws:
        got = []
        for i in range(50):
            await ws.send("jeton %d" % i); got.append(await ws.recv())
        big = "x" * 300000; await ws.send(big); r = await ws.recv()
    ok = got == ["écho:jeton %d" % i for i in range(50)] and r == "écho:" + big
    print("[WS] %s - WebSocket via le relais HTTPS :8443 : 50 messages aller-retour + message de 300 Ko" % ("OK  " if ok else "ÉCHEC"))
    srv.close()
asyncio.run(main())

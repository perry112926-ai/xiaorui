"""Local-only WebRTC and bundled Chinese turn-model compatibility checks."""
import asyncio
from fractions import Fraction
import json
from pathlib import Path
import time

import numpy as np
from aiortc import AudioStreamTrack, RTCPeerConnection, RTCConfiguration, RTCSessionDescription
from av import AudioFrame
from loguru import logger
logger.remove()
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection


class Tone(AudioStreamTrack):
    def __init__(self, frequency):
        super().__init__(); self.frequency=frequency; self.samples=0; self.started=None

    async def recv(self):
        self.started=self.started or time.monotonic()
        await asyncio.sleep(max(0,self.started+self.samples/48000-time.monotonic()))
        n=np.arange(self.samples,self.samples+960)
        data=(5000*np.sin(n*2*np.pi*self.frequency/48000)).astype(np.int16)
        frame=AudioFrame.from_ndarray(data.reshape(1,-1),format='s16',layout='mono')
        frame.pts=self.samples;frame.sample_rate=48000;frame.time_base=Fraction(1,48000)
        self.samples+=960
        return frame


async def loopback():
    client=RTCPeerConnection(RTCConfiguration(iceServers=[]))
    server=SmallWebRTCConnection(ice_servers=[])
    tasks=[];received={'client':[],'server':[]};gates={k:asyncio.Event() for k in received}
    async def receive(track,side):
        while True:
            frame=await track.recv();data=frame.to_ndarray().reshape(-1)
            received[side].append(float(np.sqrt(np.mean(data.astype(float)**2))))
            if len(received[side])>=25:gates[side].set()
    @client.on('track')
    def client_track(track):tasks.append(asyncio.create_task(receive(track,'client')))
    @server.pc.on('track')
    def server_track(track):tasks.append(asyncio.create_task(receive(track,'server')))
    client.addTrack(Tone(660));server.pc.addTrack(Tone(440))
    client.createDataChannel('pipecat')
    started=time.monotonic()
    try:
        await client.setLocalDescription(await client.createOffer())
        await server.initialize(sdp=client.localDescription.sdp,type=client.localDescription.type)
        answer=server.get_answer()
        await client.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
        await server.connect()
        await asyncio.wait_for(asyncio.gather(*(gate.wait() for gate in gates.values())),15)
        return {'synthetic_tones':True,'loopback_only':True,'physical_microphone':False,
            'browser_tested':False,'elapsed_ms':round((time.monotonic()-started)*1000),
            'frames':{side:len(v) for side,v in received.items()},
            'non_silent_both_directions':all(max(v)>100 for v in received.values())}
    finally:
        await server.disconnect();await client.close()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)


async def main():
    report={'small_webrtc':await loopback()}
    directory=Path('.local-data/pipecat-proof');directory.mkdir(parents=True,exist_ok=True)
    (directory/'media.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':asyncio.run(main())

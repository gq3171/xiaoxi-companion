#!/usr/bin/env python3
"""Run over the owner's SSH connection to issue a one-use room pairing code."""
import http.client,json,socket,ssl
from pathlib import Path
from urllib.parse import urlsplit
from deployment_paths import data_root, read_layout

def main():
    base=data_root()/'config';values={}
    for line in (base/'service.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1);values[key]=value.strip()
    origin=urlsplit(values['DESKPET_PUBLIC_ORIGIN'])
    token=values['DESKPET_COMPUTER_TOKEN'];context=ssl.create_default_context(cafile=str(base/'ca.pem'))
    with socket.create_connection(('127.0.0.1',int(read_layout()['port'])),timeout=10) as sock:
        with context.wrap_socket(sock,server_hostname=origin.hostname) as stream:
            body=b'{}';headers=('POST /v1/home/pair HTTP/1.1\r\nHost: '+origin.netloc+'\r\nAuthorization: Bearer '+token+'\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n').encode()
            stream.sendall(headers+body);response=http.client.HTTPResponse(stream);response.begin();value=json.loads(response.read(4096))
            if response.status!=200 or not value.get('ok'):raise RuntimeError('room pairing unavailable')
    print(origin.geturl()+'/home/')
    print('临时配对码：'+value['code']+'（3 分钟内有效，只用一次）')

if __name__=='__main__':main()

import base64,unittest
from desktop_transport import upgrade_headers
class UpgradeTests(unittest.TestCase):
 def headers(self):return {'Upgrade':'websocket','Connection':'keep-alive, Upgrade','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':base64.b64encode(b'x'*16).decode()}
 def test_only_valid_bounded_upgrade_can_reach_local_desktop(self):
  self.assertEqual(upgrade_headers(self.headers())['Upgrade'],'websocket')
  for key,value in [('Sec-WebSocket-Version','12'),('Sec-WebSocket-Key','invalid'),('Content-Length','1'),('Transfer-Encoding','chunked'),('Sec-WebSocket-Protocol','binary\r\nInjected: true')]:
   h=self.headers();h[key]=value
   with self.assertRaises(ValueError):upgrade_headers(h)
 def test_relay_reports_only_forwarded_byte_counts(self):
  import socket,threading
  from desktop_transport import relay
  left,client=socket.socketpair();right,server=socket.socketpair();counts=[];errors=[]
  def run():
   try:relay(left,right,seconds=2,forwarded=lambda direction,n:counts.append((direction,n)))
   except OSError as e:errors.append(type(e).__name__)
  worker=threading.Thread(target=run);worker.start()
  try:
   client.settimeout(2);server.settimeout(2);client.sendall(b'abcd');self.assertEqual(server.recv(4),b'abcd');server.sendall(b'xyz');self.assertEqual(client.recv(3),b'xyz')
  finally:client.close();worker.join(3);left.close();right.close();server.close()
  self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertEqual(counts,[(True,4),(False,3)])

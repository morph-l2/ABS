from scapy.all import *
from netfilterqueue import NetfilterQueue
import sys
from multiprocessing import Process, Manager
from MathABS import ABS
from charm.toolbox.pairinggroup import PairingGroup
import socketserver
import socket
import json
import threading
from charm.toolbox.securerandom import OpenSSLRand

def decider_of_fate(host,unknown,pkt):
    '''
    Checks whether the packet info has been previously approved and adds to
    checklist if not
    '''
    port = clientlist[host]
    clientiplist = iplist[host]
    if unknown in clientiplist:
        pkt.accept()
    else:
        triple = (host,port,unknown)
        if triple not in checklist:
            print('FIREWALL: unknown source/destination',unknown)
            checklist.append(triple)
        else:
            pkt.drop()

def print_and_accept(pkt):
    '''
    Firewall packet decider framework

    Lets uninteresting (non-HTTP, not marked to any client) packets through
    '''
    a = IP(pkt.get_payload())
    if a[IP][TCP].dport == 80:
        source,dest = a[IP].src, a[IP].dst
        host = 0
        try:
            decider_of_fate(networkalias[source],dest,pkt)
        except KeyError:
            try:
                decider_of_fate(networkalias[dest],source,pkt)
            except KeyError:
                pkt.accept()
    else:
        pkt.accept()


def FWsubprocess():
    '''
    Almost dummy subprocess for the firewall binding
    '''
    try:
        nfqueue = NetfilterQueue()
        nfqueue.bind(0,print_and_accept)
        nfqueue.run()
    except KeyboardInterrupt:
        nfqueue.unbind()


class MyTCPHandler(socketserver.BaseRequestHandler):
    '''
    Key request service that decides the client's attributes based on the
    predefined "default" and "secure" addon lists
    '''
    def handle(self):
        try:
            self.data = self.request.recv(hugeness).strip()
            msg = self.data.decode('utf-8')
            host,port = self.client_address[0],self.client_address[1]
            print('SERVER: received from {}:{} list'.format(host,port),msg)

            content = msg.split(",")
            netalias = content[0]
            addons = set(content[1:])
            attributes = []

            if addons == default_addons:
                attributes.append('DEFAULTSONLY')
            else:
                attributes.append('UNKNOWNADDONS')
                if safety_addons.issubset(addons):
                    attributes.append('SAFETYADDONSENABLED')

            ska = absinst.generateattributes(ask,attributes)
            striple = (absinst.encodestr(tpk),absinst.encodestr(apk),absinst.encodestr(ska))
            clientlist[host] = port
            networkalias[netalias] = host
            iplist[host] = valuemanager.list()
            print('SERVER: keys for {} sent, client {}:{} added to lists with netalias {}'.format(attributes,host,port, netalias))
            self.request.sendall(bytes(json.dumps(striple),'utf8'))
        except Exception as err:
            print('SERVER: MISERABLE FAILURE:',err)

class ThreadedTCPServer(socketserver.ThreadingMixIn,socketserver.TCPServer):
    pass

def checkprotocol(host,port):
    '''
    "Watchdog" runs every time there's an unknown in the list

    This is what enforces the policy
    '''
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host,int(port)))
        print('WATCHDOG: Connected to client {}:{}'.format(host,port))
        nonce = str(OpenSSLRand().getRandomBytes(20))[2:].replace("\\x","")
        stuple = (nonce,accesspolicy)
        sock.sendall(bytes(json.dumps(stuple),'utf8'))
        print('WATCHDOG: Sent nonce {} and policy {}'.format(nonce,accesspolicy))

        data = sock.recv(hugeness).strip()
        msg = data.decode('utf-8')
        signature = absinst.decodestr(msg)
        judgement = absinst.verify((tpk,apk),signature,nonce,accesspolicy)

        sock.sendall(bytes(str(judgement),'utf-8'))
        print('WATCHDOG: Sent judgement', judgement)
        return judgement
    except Exception as err:
        print(err)
        return False
    sock.close()

try:
    # HOX! run 'sudo iptables -A OUTPUT -p tcp -j NFQUEUE' before using
    attributes = [
        'DEFAULTSONLY',
        'UNKNOWNADDONS',
        'SAFETYADDONSENABLED',
    ]
    print('SERVER: ATTRIBUTE TABLE: ',attributes)
    accesspolicy = '(UNKNOWNADDONS AND SAFETYADDONSENABLED) OR DEFAULTSONLY'

    default_addons = set([
    'English (South African) Language Pack',
    'English (GB) Language Pack',
    'Application Update Service Helper',
    'Pocket',
    'Web Compat',
    'Site Deployment Checker',
    'Default',
    'Ubuntu Modifications',
    'Multi-process staged rollout',
    'Disable Prefetch',
    'Disable TLS Certificate Transparency'])
    safety_addons = set(['AdBlocker Ultimate'])

    valuemanager = Manager()
    iplist = valuemanager.dict()
    clientlist = valuemanager.dict()
    networkalias = valuemanager.dict()
    checklist = valuemanager.list()

    group = PairingGroup('SS512')
    absinst = ABS(group)
    tpk = absinst.trusteesetup(attributes)
    ask,apk = absinst.authoritysetup(tpk)

    fwp = Process(target = FWsubprocess)
    fwp.start()
    print('FIREWALL: READY')

    hugeness = 8000

    host,port = 'localhost',0
    server = ThreadedTCPServer((host,port),MyTCPHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    print('SERVER: READY, port',server.server_address[1])

    while True:
        if len(checklist)>0:
            host,port,ip = checklist.pop(0)
            if checkprotocol(host,port):
                print('WATCHDOG: ADDED',ip,'TO IPLIST')
                iplist[host].append(ip)

except KeyboardInterrupt:
    fwp.join()
    server.shutdown()
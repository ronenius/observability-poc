FROM alpine:latest

RUN apk add --no-cache net-snmp net-snmp-tools python3 py3-requests curl

WORKDIR /etc/snmp

COPY snmptrapd.conf /etc/snmp/snmptrapd.conf
COPY traphandler.py /usr/local/bin/traphandler.py

RUN chmod +x /usr/local/bin/traphandler.py

EXPOSE 162/udp 1162/udp

CMD ["/usr/sbin/snmptrapd", "-f", "-Lo", "-C", "-c", "/etc/snmp/snmptrapd.conf", "udp:162", "udp:1162"]

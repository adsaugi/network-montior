import sys
sys.path.append('/home/xs/tailscale-dashboard')
import server
server.pve_login()
status = server.pve_get('/nodes/pve1/netstat')
print(status)

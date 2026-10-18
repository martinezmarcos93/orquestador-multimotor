req(){ curl -s -m 20 http://127.0.0.1:4010/v1/chat/completions -H 'content-type: application/json' -H 'authorization: Bearer sk-test-local-4010' -d '{"model":"a","messages":[{"role":"user","content":"hi"}]}' | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['choices'][0]['message']['content'] if 'choices' in d else str(d)[:150])" ; }
cnt(){ echo "  muerto=$(curl -s 127.0.0.1:4021) bueno=$(curl -s 127.0.0.1:4020)"; }
for i in 1 2 3 4; do echo "req$i: $(req)"; cnt; done; echo "-- espero 10s (cooldown 8s)"; sleep 10; echo "req5: $(req)"; cnt

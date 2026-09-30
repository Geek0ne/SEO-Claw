#!/usr/bin/env bash
# 第二批站点的可达性预检。
#
# 为什么要单独预检：run_fp_v2.log 里出现成片的「HTTP 0」——0 是 httpx 对
# 「连接根本没建立」的报告值，不是服务器返回的状态码。如果一整批站都
# 连不通，抓取脚本仍然会逐个「成功」写出 1 页 1 条的报告（此前那版站点表
# 混进 shell 脚本时就是这样：24 站全「1 页 1 条 100.0 分」，一格没报错）。
# 花 5 秒钟先确认哪些站能通，比跑一小时拿到一堆废数据划算。
#
# 输出：每站一行 "<code> <耗时ms> <host>  <标题前 30 字>"
HOSTS="www.reddit.com
stackoverflow.com
en.wikipedia.org
en.wikibooks.org
www.bbc.com
www.reuters.com
www.nytimes.com
www.yelp.com
www.tripadvisor.com
www.imdb.com
www.goodreads.com
airbnb.com
www.booking.com
www.ikea.com
www.zalando.com
www.asos.com
www.etsy.com
www.olx.pl
www.avito.ru
spotify.com
www.netflix.com
linear.app
notion.so
www.atlassian.com
www.dropbox.com
slack.com
squareup.com
basecamp.com
mozilla.org
www.rfc-editor.org
docs.aws.amazon.com
kubernetes.io
grafana.com
www.postgresql.org
mit.edu
www.stanford.edu
www.berkeley.edu
ocw.mit.edu
www.ed.gov
www.who.int
ja.wikipedia.org
www.spiegel.de
www.lemonde.fr
www.rtve.es
www.flipkart.com
www.rakuten.co.jp
www.coupang.com"

for h in $HOSTS; do
    read -r code t < <(
        curl -s -o /tmp/rch_$h.html -w '%{http_code} %{time_total}' \
             --max-time 12 -A 'Mozilla/5.0 (compatible; SEOAgentBot/0.1)' \
             "https://$h/" 2>/dev/null || echo "000 12.0"
    )
    sz=$(wc -c < "/tmp/rch_$h.html" 2>/dev/null | tr -d ' ')
    ttl=$(grep -o -m1 '<title[^>]*>[^<]*' "/tmp/rch_$h.html" 2>/dev/null | sed 's/<[^>]*>//' | head -c 34)
    printf '%-4s %6ss %8s  %-22s %s\n' "$code" "$t" "$sz" "$h" "${ttl:-<无 title>}"
    rm -f "/tmp/rch_$h.html"
done

"""Current official-route and quote verification, separate from historical validity."""
import argparse, collections, datetime as dt, hashlib, html, json, re, time
import urllib.request, urllib.error
from urllib.parse import urlsplit
from html.parser import HTMLParser
from pathlib import Path

BASE=Path(__file__).resolve().parent
def dump(p,x):
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.canonical=None;self.published_at=None;self.embedded_strings=[];self.events=[]
    def handle_data(self,x):self.parts.append(x)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='link' and a.get('rel')=='canonical':self.canonical=a.get('href')
        if tag=='meta' and a.get('property')=='article:published_time':self.published_at=a.get('content')
        if 'data-partnereventstore' in a:
            def visit(x,depth=0):
                if depth>12:return
                if isinstance(x,dict):
                    for v in x.values():visit(v,depth+1)
                elif isinstance(x,list):
                    for v in x:visit(v,depth+1)
                elif isinstance(x,str):
                    self.embedded_strings.append(x)
                    if x[:1] in ('{','[','"'):
                        try:visit(json.loads(x),depth+1)
                        except (json.JSONDecodeError,ValueError):pass
            try:
                parsed=json.loads(a['data-partnereventstore'])
                if isinstance(parsed,list):self.events.extend(e for e in parsed if isinstance(e,dict))
                visit(parsed)
            except (json.JSONDecodeError,ValueError):pass
def norm(x):return ' '.join(html.unescape(x).split())

def bound_event_check(parser,final_url,appid,quote,published_at):
    """Bind quote/date to the requested event, never to neighboring page events."""
    canonical=urlsplit(parser.canonical or '')
    cm=re.fullmatch(r'/news/app/'+re.escape(appid)+r'/view/(\d+)/?',canonical.path) if canonical.scheme=='https' and canonical.netloc=='store.steampowered.com' else None
    final=urlsplit(final_url)
    am=re.fullmatch(r'/(?:games|ogg)/[^/]+/announcements/detail/(\d+)/?',final.path) if final.scheme=='https' and final.netloc=='steamcommunity.com' else None
    fm=re.fullmatch(r'/news/app/'+re.escape(appid)+r'/view/(\d+)/?',final.path) if final.scheme=='https' and final.netloc=='store.steampowered.com' else None
    event_gid=cm.group(1) if cm else (fm.group(1) if fm else None)
    announcement_gid=am.group(1) if am else None
    candidates=[]
    for event in parser.events:
        announcement=event.get('announcement_body')
        if not isinstance(announcement,dict) or str(event.get('appid'))!=appid:continue
        checks=[]
        if event_gid:checks.append(str(event.get('gid'))==event_gid)
        if announcement_gid:checks.append(str(announcement.get('gid'))==announcement_gid)
        if checks and all(checks):candidates.append(event)
    result={'target_event_match_count':len(candidates),'target_event_gid_expected':event_gid,'target_announcement_gid_expected':announcement_gid,'target_quote_present':False,'target_publication_matches_archived':False,'target_event_binding_rule':'Same AppID and all available canonical-event/final-announcement IDs must bind exactly one event; quote/date only from its announcement_body.'}
    if len(candidates)!=1:return result
    event=candidates[0];announcement=event['announcement_body'];body=announcement.get('body','')
    if not isinstance(body,str):return result
    try:
        actual=dt.datetime.fromtimestamp(int(announcement['posttime']),dt.timezone.utc)
        expected=dt.datetime.fromisoformat(published_at.replace('Z','+00:00'))
        date_ok=actual==expected
        timestamp=actual.isoformat()
    except (KeyError,ValueError,TypeError,OverflowError):date_ok=False;timestamp=None
    literal=quote in body;normalized=norm(quote) in norm(body)
    result.update(target_event_gid=str(event.get('gid')),target_announcement_gid=str(announcement.get('gid')),target_event_appid=str(event.get('appid')),target_announcement_body_sha256=hashlib.sha256(body.encode()).hexdigest(),target_announcement_posttime_utc=timestamp,target_publication_matches_archived=date_ok,target_quote_present=literal or normalized,target_quote_match_rule='literal' if literal else 'HTML-entity/whitespace-normalized' if normalized else 'not_present',target_event_update_time=announcement.get('updatetime'))
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--passes',nargs='+',required=True);p.add_argument('--output-stem',required=True);a=p.parse_args()
    out=BASE/'source-verification';out.mkdir(exist_ok=True);cache=out/'pages';cache.mkdir(exist_ok=True)
    excluded={str(x['appid']) for x in json.loads((BASE/'protocol/development-exclusions.frozen.json').read_text())}
    protocol=json.loads((BASE/'protocol/protocol-v3.frozen.json').read_text())
    excluded.update(str(x) for x in protocol['sampling'].get('excluded_non_game_appids',[]))
    bygame=collections.defaultdict(list);inputs={}
    for filename in a.passes:
        path=Path(filename);data=path.read_bytes();inputs[str(path)]=hashlib.sha256(data).hexdigest()
        for item in json.loads(data):bygame[str(item['appid'])].append(item)
    records=[];chosen=[];last_request=0
    for aid,leads in sorted(bygame.items(),key=lambda kv:kv[1][0]['game_order_sha256']):
        if aid in excluded:continue
        screen=BASE/'screened'/f'{aid}.summary.json'
        if not screen.exists():continue
        sums=json.loads(screen.read_text())
        for lead in sorted(leads,key=lambda x:(x['published_at_utc'],x['source_url'],x['update_snapshot_id'],x['quote_start'],x['fix_id'])):
            window=sums['windows_by_publication_date'][lead['published_at_utc'][:10]]
            if window['candidate_pairs']<20:continue
            url=lead['source_url'];key=hashlib.sha256(url.encode()).hexdigest()[:24]
            rec=dict(appid=aid,game=lead['game'],fix_id=lead['fix_id'],requested_url=url,checked_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
            page=cache/f'{key}.html';receipt=cache/f'{key}.json'
            try:
                if not page.exists():
                    time.sleep(max(0,1.15-(time.monotonic()-last_request)))
                    last_request=time.monotonic()
                    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; PatchCheck academic source verification)'})
                    with urllib.request.urlopen(req,timeout=25) as response:
                        raw=response.read(8_000_001)
                        if len(raw)>8_000_000:raise ValueError('Source page exceeds bound')
                        pr={'http_status':response.status,'final_url':response.geturl(),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'captured_at_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
                    page.write_bytes(raw);dump(receipt,pr)
                raw=page.read_bytes();pr=json.loads(receipt.read_text());assert hashlib.sha256(raw).hexdigest()==pr['sha256']
                decoded=raw.decode('utf-8','replace');parser=Text();parser.feed(decoded)
                final=pr['final_url'];official=bool(re.search(r'https://steamcommunity\.com/(?:games|ogg)/'+re.escape(aid)+r'/announcements/detail/',final) or re.search(r'https://store\.steampowered\.com/news/app/'+re.escape(aid)+r'/view/',final))
                identity_rule='numeric_app_announcement_route'
                if not official and final.startswith('https://steamcommunity.com/games/') and '/announcements/detail/' in final:
                    canonical_ok=(parser.canonical or '').startswith(f'https://store.steampowered.com/news/app/{aid}/view/')
                    app_binding=bool(re.search(r'"APPID"\s*:\s*'+re.escape(aid)+r'\s*[,}]',html.unescape(decoded)))
                    official=canonical_ok and app_binding
                    identity_rule='official_vanity_route_plus_same_app_canonical_and_APPID_binding'
                bound=bound_event_check(parser,final,aid,lead['claim_quote'],lead['published_at_utc'])
                quote_ok=bound['target_quote_present']
                rec.update(pr,**bound,official_same_app_route=official,source_identity_rule=identity_rule,canonical_url=parser.canonical,current_page_published_meta=parser.published_at,quote_present=quote_ok,quote_match_surfaces=['route_bound_announcement_body'] if quote_ok else [],quote_match_rule='literal or HTML-entity/whitespace-normalized text in uniquely route-bound announcement_body only; no neighboring-event fallback or paraphrase',html_path=str(page),historical_quote_presence='unknown',deployment_time='unknown',status='verified_current_source' if official and quote_ok and bound['target_publication_matches_archived'] and pr['http_status']==200 else 'held_source_mismatch')
                records.append(rec)
                if rec['status']=='verified_current_source':
                    chosen.append(dict(lead,source_verification=rec,window=window,raw_csv_sha256=sums['source_csv_sha256'],source_latest_review_date=sums['latest_source_date']))
                    print(len(chosen),aid,lead['fix_id'],window['candidate_pairs'],'verified',flush=True);break
                print(aid,'held',official,quote_ok,final,flush=True)
            except Exception as exc:
                rec.update(status='failed',error=type(exc).__name__+': '+str(exc));records.append(rec)
                print(aid,rec['error'],flush=True)
                if isinstance(exc,urllib.error.HTTPError) and (exc.code in (401,403,429) or exc.headers.get('Retry-After')):
                    dump(out/f'{a.output_stem}.receipts.json',records);dump(out/f'{a.output_stem}.selected.json',chosen)
                    raise RuntimeError('Stop on access/rate limit; no retries or bypass') from exc
        dump(out/f'{a.output_stem}.receipts.json',records);dump(out/f'{a.output_stem}.selected.json',chosen)
    dump(out/f'{a.output_stem}.inputs.json',{'input_sha256':inputs,'completed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'selected_games':len(chosen),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    print('selected_current_source_and_window',len(chosen),flush=True)
if __name__=='__main__':main()

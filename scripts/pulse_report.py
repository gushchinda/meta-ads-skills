"""HTML page and short text for the test pulse (see pulse.py).

Layout, top to bottom: header (snapshot, next pass) → deviations → one overview
card per project (slots, test limit, week, 30 days) → result of this pass →
stops and replacements → active tests and queue per project → queue-only
projects → sources and limits. English and Russian.
"""
import html
from datetime import timedelta

from ua_rules import common

T = {
    "en": dict(
        title="Test pulse", morning="morning rotation", snapshot="Meta snapshot", next="Next pass",
        dev="Deviations", dev_none="No deviations: slots within limits, no external pauses, no Meta errors.",
        overflow="{p}: {a}/{m} slots.", overflow_t="Manual and legacy tests occupy slots. The rotation never stops them to make room.",
        ext_pause="paused outside the rotation{r}. The pause is kept and the slot is released; the test is not resumed.",
        meta_err="Meta reports {k} on {n} ad(s) — see the project section.",
        slots_lbl="occupied / max slots", st_free="{n} free: next in line below.",
        st_free_no_queue="{n} free: no more ready folders.", st_full="All slots busy; the next folder waits for a free slot.",
        st_overflow="Slot overflow. New launches blocked; unmanaged adsets were not stopped.",
        st_queue_only="Queue only: no slots or rotation budget assigned.",
        new_tests="New tests: {n}", limit="Test limit {cap} / {d} days", daily_chk="Daily {d}; daily × {n} = {t}",
        all_daily="All active TEST: {v}/day", ltv="LTV {v} / {e}.", no_ltv="LTV not set — no cap, no launches.",
        week="Week · informational", week_spend="Actual TEST spend", guide="Guide {g}; spend {s}",
        reserve="Remaining limits of active tests {v}", left="Guide − spend − remaining {v}",
        prev="Previous week TEST spend: {v}", week_note="Weekly money never blocks a launch. Legacy remainders use the project's standard cap.",
        ready="Ready {f} folders / {c} creatives.", hold="HOLD {f} folders / {c} creatives.",
        month="30 full days", m_files="In folder · videos by file date", m_up="Uploaded · Meta videos",
        m_fin="Creatives in finished tests", m_zero="No impressions: {a}/{b} test ads created in the window; {c}/{d} ads of running managed tests. A finished test does not prove every creative got enough delivery.",
        result="Result of this pass", launched_yes="{p}: launched — yes · {n}", launched_no="{p}: launched — no.",
        campaign="Campaign {v}", folder_n="{n} creatives, folder {f}", geo="Geo: {v}", excl=" · excluded {v}",
        end="End: {v}", status="Status: {s} / {e}", next_line="{p}: next in line — {f} ({n}); {why}",
        why_dry="dry run", why_off="rotation.enabled is off — launch with launch_tests.py",
        daily_move="{p}: daily sum of active TEST after detected pauses {a} → {b}; change from new launches +{c}/day.",
        no_lifetime="No lifetime budget is set. ACTIVE means switched on; IN_PROCESS / PENDING_REVIEW do not confirm delivery. The test limit is checked on cumulative spend, it is not a hard lifetime cap in Meta.",
        stops="Stops and replacements", stop_line="{r}; spend {s}; age {a}/{d}.", repl="Replacement this pass: {v}",
        repl_none="Replacement: no ready folder; the slot stays free.", receipt="Stop rule receipt",
        no_stops="No stops this pass.", r_EARLY_STOP="paused outside the rotation (stop rule or a person)",
        r_CAP="reached the test limit — paused", r_AGE="reached the test age — paused",
        active_tests="{p} · active tests", managed="Managed test", unmanaged="Unmanaged test: occupies a slot, not stopped by the rotation",
        age_lbl="Age / {d} days", spend_lbl="Cumulative spend / cap", spend_nocap="Cumulative spend {v}; the rotation cap does not apply.",
        queue="Queue", queue_none="No ready folders.", first_seen="First seen {v}.", zero_ads="No impressions: {a}/{b} ads",
        meta_issue="Meta · {t} {c}: {s} — {n} ad(s)", queue_only="{p} · queue only",
        sources="Sources and limits",
        src1="Meta Graph API: campaigns / adsets / ads and Insights for campaigns named {pfx}…; money in account currency; the week is the calendar week of the account.",
        src2="Stops by the stop rule come from run/stop-rule.json; the rotation never pauses a test twice and never resumes one. Legacy adsets count toward slots and are never touched.",
        src3="'In folder' counts videos by file date — synced drives may re-stamp dates. 'Uploaded' counts Meta video objects; the same file uploaded twice counts twice.",
        dry="DRY RUN — nothing was changed", none="—", per_day="/day", proj_summary="slots {a}/{m}"),
    "ru": dict(
        title="Пульс тестов", morning="утренняя ротация", snapshot="Срез Meta", next="Следующий проход",
        dev="Отклонения", dev_none="Отклонений нет: слоты в пределах, внешних пауз и ошибок Meta нет.",
        overflow="{p}: {a}/{m} слотов.", overflow_t="Ручные и legacy-тесты занимают места. Ротация не выключает их ради новых заливок.",
        ext_pause="остановлен вне ротации{r}. Подтверждённая пауза сохранена и освободила слот; тест обратно не включался.",
        meta_err="Meta сообщает {k} по {n} объявл. — подробности в разделе проекта.",
        slots_lbl="занято / максимум слотов", st_free="Свободно {n}: следующие в очереди ниже.",
        st_free_no_queue="Свободно {n}: больше готовых папок нет.", st_full="Все слоты заняты; следующая папка ждёт освобождения места.",
        st_overflow="Переполнение слотов. Новые заливки заблокированы; неуправляемые адсеты не останавливались.",
        st_queue_only="Только очередь: слоты и бюджет ротации не назначены.",
        new_tests="Новых тестов: {n}", limit="Лимит теста {cap} / {d} дней", daily_chk="Daily {d}; daily × {n} = {t}",
        all_daily="Все действующие TEST: {v}/день", ltv="LTV {v} / {e}.", no_ltv="LTV не задан — нет лимита и запусков.",
        week="Неделя · справочно", week_spend="Фактический расход TEST", guide="Ориентир {g}; расход {s}",
        reserve="Остатки лимитов действующих тестов {v}", left="Ориентир − расход − остатки {v}",
        prev="Расход TEST прошлой недели: {v}", week_note="Недельные деньги не блокируют запуск. Остатки legacy рассчитаны справочно по стандартному cap проекта.",
        ready="Готовы {f} папок / {c} креативов.", hold="HOLD {f} папок / {c} креативов.",
        month="30 полных дней", m_files="В папке · видео по дате файла", m_up="Залито · видео в Meta",
        m_fin="Креативы в завершённых тестах", m_zero="Без показов: {a}/{b} объявлений тестов, созданных в окне; {c}/{d} объявлений действующих управляемых тестов. Завершение теста не доказывает достаточную доставку каждого креатива.",
        result="Результат текущего прохода", launched_yes="{p}: запущен — да · {n}", launched_no="{p}: запущен — нет.",
        campaign="Кампания {v}", folder_n="{n} креативов, папка {f}", geo="Гео: {v}", excl=" · исключены {v}",
        end="Конец: {v}", status="Статус: {s} / {e}", next_line="{p}: следующая в очереди — {f} ({n}); {why}",
        why_dry="сухой прогон", why_off="rotation.enabled выключен — запуск через launch_tests.py",
        daily_move="{p}: дневная сумма действующих TEST после обнаруженных пауз {a} → {b}; изменение от новых запусков +{c}/день.",
        no_lifetime="Lifetime budget не задан. ACTIVE означает «включён»; IN_PROCESS / PENDING_REVIEW не подтверждают показы. Лимит теста проверяется по накопленному расходу, это не жёсткий lifetime cap в Meta.",
        stops="Остановки и замены", stop_line="{r}; расход {s}; возраст {a}/{d}.", repl="Замена в этом проходе: {v}",
        repl_none="Замена: готовой папки нет; слот свободен.", receipt="Квитанция правила стопа",
        no_stops="Остановок в этом проходе нет.", r_EARLY_STOP="остановлен вне ротации (правило стопа или человек)",
        r_CAP="исчерпан лимит теста — пауза", r_AGE="истёк срок теста — пауза",
        active_tests="{p} · действующие тесты", managed="Управляемый тест", unmanaged="Неуправляемый тест: занимает слот, не останавливается ротацией",
        age_lbl="Возраст / {d} дней", spend_lbl="Накопленный расход / cap", spend_nocap="Накопленный расход {v}; cap ротации не применяется.",
        queue="Очередь", queue_none="Готовых папок нет.", first_seen="Первое обнаружение {v}.", zero_ads="Без показов: {a}/{b} объявлений",
        meta_issue="Meta · {t} {c}: {s} — {n} объявл.", queue_only="{p} · только очередь",
        sources="Источники и ограничения",
        src1="Meta Graph API: campaigns / adsets / ads и Insights кампаний с префиксом {pfx}…; деньги в валюте кабинета; неделя — календарная неделя кабинета.",
        src2="Остановки правилом стопа берутся из run/stop-rule.json; ротация не выключает тест повторно и не включает обратно. Legacy-адсеты занимают слоты и не трогаются.",
        src3="«В папке» считает видео по дате файла — синхронизация диска может её переписать. «Залито» считает видео-объекты Meta; один файл, залитый дважды, считается дважды.",
        dry="СУХОЙ ПРОГОН — ничего не менялось", none="—", per_day="/день", proj_summary="слоты {a}/{m}"),
}

CSS = """
:root{--bg:#eef5fd;--card:#fff;--soft:#e3effb;--ink:#173a5e;--mute:#5b7089;--line:#c9dcf0;--acc:#3a7bd5;--track:#c8dcf1;
--hero:#1a4f8f;--hero-ink:#fff;--warnbg:#fff1d6;--warnline:#f0d9a8;--bad:#b3261e;--ok:#24724a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1722;--card:#16212f;--soft:#1b2a3c;--ink:#e3edf8;--mute:#9db0c6;
--line:#2a3d55;--acc:#6aa3f0;--track:#2a3d55;--hero:#173a66;--warnbg:#3a2f17;--warnline:#5a4a24;--bad:#ff8a80;--ok:#7fd6a4}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif}
main{max-width:1060px;margin:0 auto;padding:24px 16px 40px}.mono{font:11px/1.3 ui-monospace,Menlo,monospace;color:var(--mute);word-break:break-all}
.hero{background:var(--hero);color:var(--hero-ink);border-radius:18px;padding:26px 28px}.hero h1{margin:0 0 14px;font-size:34px}.hero p{margin:4px 0}
.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin:18px 0}
.warn{background:var(--warnbg);border-color:var(--warnline)}.warn h2{margin-top:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin:18px 0}
.pc{background:var(--soft);border:1px solid var(--line);border-radius:16px;padding:20px}
.ph{display:flex;align-items:center;gap:12px}.ph img,.ph .ini{width:44px;height:44px;border-radius:11px;flex:none}
.ini{display:grid;place-items:center;background:var(--acc);color:#fff;font-weight:700;font-size:20px}
.ph h3{margin:0;font-size:22px}.big{font-size:40px;font-weight:800;margin:10px 0 0;letter-spacing:.5px}
.seg{display:flex;gap:5px;margin:10px 0 14px}.seg i{flex:1;height:10px;border-radius:3px;background:var(--track)}.seg i.on{background:var(--acc)}.seg i.over{background:var(--bad)}
.note{background:var(--card);border-radius:10px;padding:10px 14px;margin:0 0 12px}
h4{margin:18px 0 8px;font-size:17px}.kv{display:flex;justify-content:space-between;gap:10px;font-size:13px;color:var(--mute)}.kv b{color:var(--ink);white-space:nowrap}
.bar{height:9px;border-radius:5px;background:var(--track);overflow:hidden;margin:6px 0 10px}.bar i{display:block;height:100%;background:var(--acc)}
.small{font-size:12.5px;color:var(--mute)}.lines p{margin:2px 0}
.item{border-top:1px solid var(--line);padding:14px 0}.item:first-of-type{border-top:0}
.hl{background:var(--warnbg);padding:6px 10px;border-radius:6px;margin:6px 0}
details summary{cursor:pointer;margin:6px 0}footer{color:var(--mute);font-size:13px;margin-top:10px}
"""


def _e(v):
    return html.escape(str(v))


def _bar(v, top):
    pct = 0 if not top else max(0, min(100, 100 * v / top))
    return f'<div class=bar><i style="width:{pct:.1f}%"></i></div>'


def _t(lang):
    return T.get(lang, T["en"])


def _fmt_dt(dt, tz):
    s = f"{dt:%d.%m.%Y %H:%M} UTC"
    if tz:
        try:
            from zoneinfo import ZoneInfo
            s = f"{dt.astimezone(ZoneInfo(tz)):%d.%m.%Y %H:%M} {tz.split('/')[-1].replace('_', ' ')} / {dt:%H:%M} UTC"
        except Exception:  # noqa: BLE001
            pass
    return s


def _geo(g, x, t):
    return (", ".join(g) or t["none"]) + (t["excl"].format(v=", ".join(x)) if x else "")


def _events(ev):
    return " · ".join(f"{k} {v}" for k, v in ev.items())


def summary(res, dry, lang="en"):
    t, pj = _t(lang), res["pj"]
    m = lambda v: common.money(pj, v)  # noqa: E731
    s = res["slots"]
    out = [f"<b>{pj['name']}</b> · {t['title'].lower()} · {t['proj_summary'].format(a=s['active'], m=s['max'])}"]
    out.append(t["st_" + res["slot_state"]].format(n=s["free"]))
    for e in res["ended"]:
        out.append(f"⏹ {e['folder']} — {t['r_' + e['reason']]} · {m(e['spend'])}")
    for x in res["launched"]:
        out.append(f"▶️ {x['name']} · {x['count']} · {m(res['daily'])}{t['per_day']}")
    for x in res["proposed"]:
        out.append("⏭ " + t["next_line"].format(p=pj["name"], f=x["folder"], n=x["count"],
                                                why=t["why_dry"] if dry else t["why_off"]))
    w = res["week"]
    out.append(f"{t['week_spend']}: {m(w['spend'])}" + (f" / {m(w['guide'])}" if w["guide"] else ""))
    out += [f"⚠️ {x}" for x in res["errors"]]
    return "\n".join(out)


def _deviations(results, t):
    rows = []
    for r in results:
        p, s = r["pj"]["name"], r["slots"]
        if r["slot_state"] == "overflow":
            rows.append(f"<p><b>{_e(t['overflow'].format(p=p, a=s['active'], m=s['max']))}</b> {_e(t['overflow_t'])}</p>")
        for e in r["ended"]:
            if e["reason"] == "EARLY_STOP":
                rc = e["receipt"].get("lead_result") or {}
                why = f" — {rc.get('test')}: {rc.get('events')} ≤ {rc.get('threshold')}" if rc else ""
                rows.append(f"<p><b>{_e(p)} · {_e(e['folder'])}:</b> "
                            f"{_e(t['ext_pause'].format(r=why))}</p>")
        for i in r["issues"]:
            rows.append(f"<p><b>{_e(p)}:</b> {_e(t['meta_err'].format(k=(i['type'] + ' ' + i['code']).strip(), n=i['ads']))}</p>")
        rows += [f"<p><b>{_e(p)}:</b> {_e(x)}</p>" for x in r["errors"]]
    body = "".join(rows) or f"<p>{_e(t['dev_none'])}</p>"
    return f"<section class='box{' warn' if rows else ''}'><h2>⚠️ {_e(t['dev'])}</h2>{body}</section>" if rows else \
        f"<section class=box><h2>{_e(t['dev'])}</h2>{body}</section>"


def _overview(r, t):
    pj, s = r["pj"], r["slots"]
    m = lambda v: common.money(pj, v)  # noqa: E731
    icon = (f"<img src='{_e(pj['icon'])}' alt=''>" if pj.get("icon") else f"<span class=ini>{_e(pj['name'][:1].upper())}</span>")
    out = [f"<div class=pc><div class=ph>{icon}<div><h3>{_e(pj['name'])}</h3>"
           f"<div class=small>{_e(r['tz'] or '')}{' · ' if r['tz'] else ''}{_e(r['currency'])}</div></div></div>"]
    if r["mode"] == "queue_only":
        out.append(f"<div class=note>{_e(t['st_queue_only'])}</div>")
    else:
        segs = "".join(f"<i class={'over' if s['active'] > s['max'] and i >= s['max'] - (s['active'] - s['max']) else ('on' if i < s['active'] else '')}></i>"
                       for i in range(s["max"]))
        out.append(f"<div class=big>{s['active']} / {s['max']}</div><div>{_e(t['slots_lbl'])}</div><div class=seg>{segs}</div>"
                   f"<div class=note>{_e(t['st_' + r['slot_state']].format(n=s['free']))}</div><div class=lines>"
                   f"<p>{_e(t['new_tests'].format(n=s['new']))}</p>")
        if r["cap"]:
            out.append(f"<p>{_e(t['limit'].format(cap=m(r['cap']), d=r['days']))}</p>"
                       f"<p>{_e(t['daily_chk'].format(d=m(r['daily']), n=r['days'], t=m(r['daily'] * r['days'])))}</p>")
        out.append(f"<p>{_e(t['all_daily'].format(v=m(r['daily_after'])))}</p></div>")
    out.append(f"<p>{_e(t['ltv'].format(v=m(pj['ltv']), e=pj['conversion_event']) if pj['ltv'] else t['no_ltv'])}</p>")
    w = r["week"]
    guide_txt = f" / {w['guide']:,.0f}" if w["guide"] else ""
    out.append(f"<h4>{_e(t['week'])}</h4><div class=kv><span>{_e(t['week_spend'])}, {_e(r['currency'])}</span>"
               f"<b>{w['spend']:,.2f}{guide_txt}</b></div>"
               f"{_bar(w['spend'], w['guide'] or w['spend'] or 1)}<div class=lines>"
               f"<p>{w['since']:%Y-%m-%d} — {w['until']:%Y-%m-%d}</p>"
               + (f"<p>{_e(t['guide'].format(g=m(w['guide']), s=m(w['spend'])))}</p>" if w["guide"] else "")
               + f"<p>{_e(t['reserve'].format(v=m(w['reserve'])))}</p>"
               + (f"<p>{_e(t['left'].format(v=m(w['left'])))}</p>" if w["left"] is not None else "")
               + f"<p>{_e(t['prev'].format(v=m(w['prev'])))}</p></div><p class=small>{_e(t['week_note'])}</p>")
    ready = [q for q in r["queue"] if not q["hold"]]
    held = [q for q in r["queue"] if q["hold"]]
    out.append(f"<div class=lines><p>{_e(t['ready'].format(f=len(ready), c=sum(q['count'] for q in ready)))}</p>"
               f"<p>{_e(t['hold'].format(f=len(held), c=sum(q['count'] for q in held)))}</p></div>")
    mo = r["month"]
    tgt = mo["target"]
    out.append(f"<h4>{_e(t['month'])}</h4><p class=small>{mo['since']:%Y-%m-%d} — {mo['until']:%Y-%m-%d}</p>")
    for lbl, v in ((t["m_files"], mo["files"]), (t["m_up"], mo["uploaded"]), (t["m_fin"], mo["finished"])):
        if v is None:
            continue
        out.append(f"<div class=kv><span>{_e(lbl)}</span><b>{v}{f' / {tgt}' if tgt else ''}</b></div>"
                   + (_bar(v, tgt) if tgt else ""))
    out.append(f"<p class=small>{_e(t['m_zero'].format(a=mo['zero_window'][0], b=mo['zero_window'][1], c=mo['zero_managed'][0], d=mo['zero_managed'][1]))}</p></div>")
    return "".join(out)


def _result(results, t, dry):
    out = [f"<section class=box><h2>{_e(t['result'])}</h2>"]
    for r in results:
        if r["mode"] == "queue_only":
            continue
        pj = r["pj"]
        m = lambda v, p=pj: common.money(p, v)  # noqa: E731
        for x in r["launched"]:
            out.append(f"<div class=item><b>{_e(t['launched_yes'].format(p=pj['name'], n=x['name']))}</b>"
                       f"<div class=mono>{_e(x['id'])}</div><div class=lines>"
                       f"<p>{_e(t['campaign'].format(v=x['campaign_id']))}</p><p>{_e(t['folder_n'].format(n=x['count'], f=x['folder']))}</p>"
                       f"<p>{_e(t['limit'].format(cap=m(r['cap']), d=r['days']))}; {_e(t['daily_chk'].format(d=m(r['daily']), n=r['days'], t=m(r['daily'] * r['days'])))}</p>"
                       f"<p>{_e(t['geo'].format(v=_geo(x['geo'], x['excluded'], t)))}</p><p>{_e(t['end'].format(v=x['end']))}</p>"
                       f"<p>{_e(t['status'].format(s=x['status'], e=x['effective_status']))}</p></div></div>")
        if not r["launched"]:
            out.append(f"<div class=item><b>{_e(t['launched_no'].format(p=pj['name']))}</b> {_e(t['st_' + r['slot_state']].format(n=r['slots']['free']))}")
            if r["cap"]:
                out.append(f" {_e(t['limit'].format(cap=m(r['cap']), d=r['days']))}, {_e(m(r['daily']))}{_e(t['per_day'])}.")
            out.append("</div>")
        for x in r["proposed"]:
            out.append(f"<p class=hl>{_e(t['next_line'].format(p=pj['name'], f=x['folder'], n=x['count'], why=t['why_dry'] if dry else t['why_off']))}</p>")
        out.append(f"<p>{_e(t['daily_move'].format(p=pj['name'], a=m(r['daily_before']), b=m(r['daily_after']), c=m(r['daily_after'] - r['daily_before'])))}</p>")
    out.append(f"<p class=small>{_e(t['no_lifetime'])}</p></section>")
    return "".join(out)


def _stops(results, t):
    out = [f"<section class=box><h2>{_e(t['stops'])}</h2>"]
    n = 0
    for r in results:
        pj = r["pj"]
        for e in r["ended"]:
            n += 1
            rep = e["replacement"]
            out.append(f"<div class=item><b>{_e(pj['name'])} · {_e(e['folder'])}</b> <span class=mono>{_e(e['id'])}</span>"
                       f"<p>{_e(t['stop_line'].format(r=t['r_' + e['reason']], s=common.money(pj, e['spend']), a=e['age'], d=e['days']))}"
                       f"{' (dry)' if e['dry'] else ''}</p>"
                       f"<p>{_e(t['repl'].format(v=rep['folder'] + ' · ' + rep['id']) if rep else t['repl_none'])}</p>")
            if e["receipt"]:
                rc = e["receipt"]
                lr = rc.get("lead_result") or {}
                body = "".join(f"<p>{_e(k)}: {_e(v)}</p>" for k, v in (
                    ("paused_at", rc.get("paused_at")), ("test", lr.get("test")),
                    ("events", lr.get("events")), ("threshold", lr.get("threshold"))) if v is not None)
                out.append(f"<details><summary>{_e(t['receipt'])}</summary><div class=small>{body}</div></details>")
            out.append("</div>")
    if not n:
        out.append(f"<p>{_e(t['no_stops'])}</p>")
    out.append("</section>")
    return "".join(out)


def _tests(r, t):
    pj = r["pj"]
    m = lambda v: common.money(pj, v)  # noqa: E731
    out = [f"<section class=box><h2>{_e(t['active_tests'].format(p=pj['name']))}</h2>"]
    for x in r["tests"]:
        zero = x["ads"] - x["delivered"] if x["age"] >= 1 else 0
        out.append(f"<div class=item><b>{_e(x['name'])}</b><div class=mono>{_e(x['id'])}</div><div class=lines>"
                   f"<p>{_e(x['status'])} / {_e(x['effective_status'])}</p><p>{_e(t['campaign'].format(v=x['campaign_id']))}</p>"
                   f"<p>{_e(t['geo'].format(v=_geo(x['geo'], x['excluded'], t)))}</p><p>Daily {_e(m(x['daily']))}</p>"
                   f"<p>{_e(t['managed'] if x['managed'] else t['unmanaged'])}</p></div>"
                   f"<div class=kv style='margin-top:10px'><span>{_e(t['age_lbl'].format(d=x['days']))}</span><b>{x['age']:g} / {x['days']}</b></div>{_bar(x['age'], x['days'])}")
        if x["managed"] and x["cap"]:
            out.append(f"<div class=kv><span>{_e(t['spend_lbl'])}</span><b>{x['spend']:,.2f} / {x['cap']:g}</b></div>{_bar(x['spend'], x['cap'])}")
        else:
            out.append(f"<p>{_e(t['spend_nocap'].format(v=m(x['spend'])))}</p>")
        out.append(f"<p>{_e(_events(x['events']))}</p>")
        if zero > 0:
            out.append(f"<p class=small>{_e(t['zero_ads'].format(a=zero, b=x['ads']))}</p>")
        out.append("</div>")
    out.append(_queue(r, t))
    for i in r["issues"]:
        out.append(f"<p class=hl>{_e(t['meta_issue'].format(t=i['type'], c=i['code'], s=i['summary'], n=i['ads']))}</p>")
    out.append("</section>")
    return "".join(out)


def _queue(r, t):
    out = [f"<h4>{_e(t['queue'])}</h4>"]
    if not r["queue"]:
        return out[0] + f"<p>{_e(t['queue_none'])}</p>"
    for q in r["queue"]:
        out.append(f"<div style='margin:8px 0'>{_e(q['folder'])} · {q['count']} · {'HOLD' if q['hold'] else 'QUEUED'}"
                   f"<div class=small>{_e(t['first_seen'].format(v=q['first_seen'][:16].replace('T', ' ')))}</div></div>")
    return "".join(out)


def html_page(results, now, dry, lang="en", tz=None):
    t = _t(lang)
    rot = [r for r in results if r["mode"] == "rotation"]
    qonly = [r for r in results if r["mode"] == "queue_only"]
    pfx = sorted({r["pj"]["testing"]["campaign_prefix"] for r in results}) or ["TEST"]
    parts = [f"<!doctype html><html lang={lang}><head><meta charset=utf-8>"
             f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{_e(t['title'])} {now:%d.%m.%Y}</title>"
             f"<style>{CSS}</style></head><body><main>",
             f"<header class=hero><h1>{_e(t['title'])}</h1><p>{now:%d.%m.%Y} · {_e(t['morning'])}"
             f"{' · ' + _e(t['dry']) if dry else ''}</p><p>{_e(t['snapshot'])}: {_e(_fmt_dt(now, tz))}</p>"
             f"<p>{_e(t['next'])}: {_e(_fmt_dt(now + timedelta(days=1), tz))}</p></header>",
             _deviations(results, t)]
    if rot:
        parts.append("<div class=cards>" + "".join(_overview(r, t) for r in rot) + "</div>")
        parts.append(_result(rot, t, dry))
        parts.append(_stops(rot, t))
        parts += [_tests(r, t) for r in rot]
    for r in qonly:
        parts.append(f"<section class=box><h2>{_e(t['queue_only'].format(p=r['pj']['name']))}</h2>{_queue(r, t)}</section>")
    parts.append(f"<section class=box><h2>{_e(t['sources'])}</h2><p>{_e(t['src1'].format(pfx='/'.join(pfx)))}</p>"
                 f"<p>{_e(t['src2'])}</p><p>{_e(t['src3'])}</p></section>"
                 f"<footer>test-pulse · {now:%Y-%m-%dT%H:%M}Z</footer></main></body></html>")
    return "".join(parts)

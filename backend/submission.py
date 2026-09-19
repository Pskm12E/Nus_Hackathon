"""Prepare and inspect PS1 CSV content without packaging or submitting it."""
from collections import defaultdict
from .domain import csv_text, csv_rows

HEADERS={
    'SCHEDULE_ACCESS.csv':['activity_id','access_seq','week','eclo','access_night'],
    'SCHEDULE_OCCUPANCY.csv':['activity_id','week','location_id','co_share_group'],
    'RESULTS.csv':['scenario','contract_number','simulated_completion_date','overrun_days'],
}


def closure_violations(instance, occupancy):
    """Check the weekly possession graph encoded in the exported CSV.

    Sharing at any (location, week, group) joins activities into one possession.
    Members are exempt from that possession's combined closure; external jobs
    are not, even if their internal calendar nights differ. This interpretation
    reproduces the 49 organiser-reported errors in our rejected Scenario A and
    reports no closure errors for the organiser's published sample. It is a
    local regression check, not the unpublished reference validator.
    """
    acts={a['activity_id']:a for a in instance['activities']}
    groups=defaultdict(set); weeks=defaultdict(set)
    for row in occupancy:
        aid=row['activity_id']; week=int(row['week'])
        groups[week,row['location_id'],row['co_share_group']].add(aid)
        weeks[week].add(aid)
    violations=[]
    for week,ids in sorted(weeks.items()):
        parent={aid:aid for aid in ids}
        def root(aid):
            while parent[aid]!=aid:
                parent[aid]=parent[parent[aid]]
                aid=parent[aid]
            return aid
        for (w,_,_),members in groups.items():
            if w!=week: continue
            members=sorted(members)
            for aid in members[1:]: parent[root(aid)]=root(members[0])
        possessions=defaultdict(set)
        for aid in sorted(ids): possessions[root(aid)].add(aid)
        for members in possessions.values():
            closure=set().union(*(acts[aid]['footprint'] for aid in members))
            for aid in sorted(ids-members):
                hit=sorted(set(acts[aid]['locations']) & closure)
                if hit:
                    violations.append(dict(rule='closure',detail=f'wk{week}: {aid} inside closure of {sorted(members)[:3]} at {hit[:4]}'))
    return violations


def tables(instance, plan):
    granted=defaultdict(set)
    for r in plan['accesses']: granted[r['contract_number'],r['activity_type'],r['week']].add(r['night'])
    activities={a['activity_id']:a for a in instance['activities']}
    access=[]; occupancy=[]
    for r in plan['accesses']:
        nights=sorted(granted[r['contract_number'],r['activity_type'],r['week']])
        access.append(dict(r,access_night=nights.index(r['night'])+1))
        for loc in activities[r['activity_id']]['locations']:
            occupancy.append(dict(activity_id=r['activity_id'],week=r['week'],location_id=loc,co_share_group=f'n{r["night"]}'))
    results=[dict(scenario=plan['scenario'],contract_number=c['contract_number'],simulated_completion_date=c['completion_date'],overrun_days=c['overrun_days']) for c in plan['contracts']]
    return dict(zip(HEADERS,[access,occupancy,results]))


def inspect_submission(instance, plan):
    content={name:csv_text(rows,HEADERS[name]) for name,rows in tables(instance,plan).items()}
    parsed={name:csv_rows(text) for name,text in content.items()}
    acts={a['activity_id']:a for a in instance['activities']}
    workload=defaultdict(float); weekly=defaultdict(set); workfronts=defaultdict(set)
    violations=[v['detail'] for v in closure_violations(instance,parsed['SCHEDULE_OCCUPANCY.csv'])]
    for r in parsed['SCHEDULE_ACCESS.csv']:
        a=acts[r['activity_id']]; p=instance['projects'][a['contract_number']]
        night=int(r['access_night']); w=int(r['week'])
        if not 1<=night<=p['number_of_maximum_access_per_week']: violations.append('access_night outside granted range')
        workload[a['activity_id']]+=1.5 if r['eclo']=='1' else 1
        weekly[a['activity_id']].add(w)
        workfronts[a['contract_number'],a['activity_type'],w,night].add(a['activity_id'])
    if any(workload[aid]<a['total_accesses'] for aid,a in acts.items()): violations.append('Full workload is not represented')
    if any(len(ids)>instance['projects'][cid]['number_of_workfronts'] for (cid,_,_,_),ids in workfronts.items()): violations.append('Workfront cap exceeded')
    expected={(aid,w,loc) for aid,weeks in weekly.items() for w in weeks for loc in acts[aid]['locations']}
    actual=[(r['activity_id'],int(r['week']),r['location_id']) for r in parsed['SCHEDULE_OCCUPANCY.csv']]
    if set(actual)!=expected or len(actual)!=len(set(actual)): violations.append('Occupancy footprint is incomplete or duplicated')
    if {r['contract_number'] for r in parsed['RESULTS.csv']}!=set(instance['projects']): violations.append('Missing contract results')
    if any(r['scenario']!=plan['scenario'] for r in parsed['RESULTS.csv']): violations.append('Mixed scenarios')
    return dict(passed=not violations and plan['audit']['passed'],official_validator=False,packaged=False,
                violations=violations,files=[dict(name=name,columns=HEADERS[name],rows=len(rows)) for name,rows in parsed.items()],
                checks=['Exact CSV headers','Full activity workload','Local contract/type/week access-night indices','Workfront caps after index conversion','Complete, unique occupancy rows','Weekly possession-group closures after CSV conversion','One scenario and all contracts in results'],
                explanation='In-memory CSV round-trip and PLiZ local audit only. No ZIP was generated or uploaded. The organiser’s validator is not published in the repository.')

"""Prepare and inspect PS1 CSV content without packaging or submitting it."""
from collections import defaultdict
from .domain import csv_text, csv_rows

HEADERS={
    'SCHEDULE_ACCESS.csv':['activity_id','access_seq','week','eclo','access_night'],
    'SCHEDULE_OCCUPANCY.csv':['activity_id','week','location_id','co_share_group'],
    'RESULTS.csv':['scenario','contract_number','simulated_completion_date','overrun_days'],
}


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
    violations=[]
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
                checks=['Exact CSV headers','Full activity workload','Local contract/type/week access-night indices','Workfront caps after index conversion','Complete, unique occupancy rows','One scenario and all contracts in results'],
                explanation='In-memory CSV round-trip and PLiZ local audit only. No ZIP was generated or uploaded. The organiser’s validator is not published in the repository.')

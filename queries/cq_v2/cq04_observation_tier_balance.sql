with totals as (
  select stage_code,count(*) total from research_culture_states group by stage_code
)
select s.stage_order,s.stage_code,s.stage_label_zh,s.observation_tier,count(*) state_count,
       round(1.0*count(*)/t.total,6) state_share
from research_culture_states s join totals t using(stage_code)
group by s.stage_order,s.stage_code,s.stage_label_zh,s.observation_tier,t.total
order by s.stage_order,s.observation_tier;

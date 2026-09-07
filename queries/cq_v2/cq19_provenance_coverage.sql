select a.research_tier,count(distinct a.fact_id) assertion_count,count(p.provenance_id) provenance_count,
       sum(case when p.provenance_id is null then 1 else 0 end) assertions_without_provenance,
       round(1.0*count(p.provenance_id)/count(distinct a.fact_id),6) average_sources_per_assertion
from research_assertions a left join research_assertion_provenance p using(fact_id)
group by a.research_tier
order by a.research_tier;

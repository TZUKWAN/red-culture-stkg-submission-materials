select research_tier,semantic_status,count(*) assertion_count,sum(source_member_count) source_member_count,
       sum(case when time_start is not null then 1 else 0 end) time_known_count,
       sum(case when canonical_space_anchor_id is not null then 1 else 0 end) space_known_count
from research_assertions
group by research_tier,semantic_status
order by research_tier,semantic_status;

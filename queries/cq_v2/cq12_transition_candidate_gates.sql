select publication_gate_reason,publication_eligible,count(*) candidate_count,
       count(distinct from_state_id||char(31)||to_state_id) distinct_state_pairs,
       count(distinct supporting_fact_id) distinct_supporting_facts
from research_evolution_transition_candidates
group by publication_gate_reason,publication_eligible
order by publication_eligible desc,candidate_count desc;

import { auditDetails } from '../src/utils/audit.ts'
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { createMeasurementPayload, updateMeasurementPayload, focusNextRoot, nextPendingTask, taskSearchMatches } from '../src/features/measurement/utils/measurement.ts'
import { sowingSearchMatches } from '../src/features/germination/utils/sowingSearch.ts'
const form={root:'0',shoot:'',rootNA:false,shootNA:true,measuredAt:'2026-09-30T10:30',notes:'核对'}
test('create carries identity, PATCH carries only editable values and keeps 0/NA',()=>{
 const update=updateMeasurementPayload(form), create=createMeasurementPayload({sample_id:'s',timepoint_id:'t'},form)
 assert.equal(create.sample_id,'s'); assert.equal(create.timepoint_id,'t')
 assert.equal('sample_id' in update,false); assert.equal('timepoint_id' in update,false)
 assert.equal(update.root_length_mm,0);assert.equal(update.shoot_length_mm,null);assert.equal(update.shoot_unavailable,true)
})
test('next pending task becomes the target before nextTick focuses its root input',async()=>{
 const tasks=[{sample_id:'first',status:'completed'},{sample_id:'next',status:'overdue',day_after_germination:7},{sample_id:'last',status:'due_today',day_after_germination:3}]
 const selected=nextPendingTask(tasks);assert.equal(selected.sample_id,'next');assert.equal(nextPendingTask(tasks,3).sample_id,'last')
 const events=[];await focusNextRoot(async()=>{events.push('render:'+selected.sample_id)},()=>events.push('root:'+selected.sample_id)); assert.deepEqual(events,['render:next','root:next'])
})
test('normal search accepts numbers, hyphens and Chinese while preserving current form',()=>{
 const task={experiment_number:'001',field_number:'001-1',taxon_common_name:'阿尔泰狗娃花',taxon_scientific_name:'Aster altaicus',sample_number:3}
 const before=structuredClone(form)
 for(const q of ['001','001-1','阿尔泰','Aster','幼苗 03'])assert.equal(taskSearchMatches(task,q),true)
 assert.deepEqual(form,before)
 const source=readFileSync(new URL('../src/features/measurement/components/SeedlingMeasurementWorkbench.vue',import.meta.url),'utf8')
 assert.match(source,/v-model="search"/)
 const searchWatcher=source.slice(source.indexOf('watch([search'),source.indexOf('watch(page'))
 assert.doesNotMatch(searchWatcher,/reset|confirmDiscard|selected/)
})
test('sowing search finds padded experiment and field numbers and species',()=>{
 const material={experiment_number:1,preview_number:1,taxon_common_name:'狗尾草',taxon_scientific_name:'Setaria viridis',seed_lot_code:'LOT-1',source_code:null}, dishes=[{field_number:'001-1'}]
 for(const q of ['001','001-1','狗尾草','Setaria'])assert.equal(sowingSearchMatches(material,dishes,q),true)
 assert.equal(sowingSearchMatches(material,dishes,'002'),false)
 assert.equal(sowingSearchMatches({...material,experiment_number:2},[{field_number:'002-1'}],'002'),true)
})

test('audit details show business fields, zero and NA without identity or raw JSON',()=>{
 const result=auditDetails({entity_type:'SeedlingMeasurement',before:{sample_id:'hidden',root_length_mm:0,shoot_length_mm:2,shoot_unavailable:false},after:{sample_id:'hidden',root_length_mm:4.2,shoot_length_mm:null,shoot_unavailable:true}})
 assert.deepEqual(result.find(row=>row.label==='根长（mm）'),{label:'根长（mm）',before:'0',after:'4.2'})
 assert.equal(result.find(row=>row.label==='苗长（mm）').after,'NA');assert.equal(result.some(row=>row.label==='sample_id'),false)
 const status=auditDetails({entity_type:'GerminationDish',before:{status:'planned'},after:{status:'cancelled'}})[0]
 assert.equal(status.before,'待置床');assert.equal(status.after,'已取消')
})

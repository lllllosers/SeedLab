import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { measurementQueryParams, normalizedDag } from '../src/features/measurement/utils/measurementQuery.ts'
import { orderedMaterials, selectedMaterialPage } from '../src/features/germination/utils/materialSelection.ts'
import { saveMaterialPrefill, readMaterialPrefill, resolveMaterialPrefill, clearMaterialPrefill, MATERIAL_PREFILL_KEY } from '../src/features/germination/utils/materialPrefill.ts'
import { updateMeasurementPayload } from '../src/features/measurement/utils/measurement.ts'

const lots = Array.from({length:200}, (_,n)=>({id:String(n),sort_rank:n+1,code:`LOT-${n}`,taxon_common_name:`材料${n}`}))
const source=(path)=>readFileSync(new URL('../src/'+path,import.meta.url),'utf8')
test('selected material preview has stable numbering, deduplicated add/remove and 25/50/100 pages',()=>{
 const selected=orderedMaterials([...lots.slice().reverse(),lots[0]])
 assert.equal(selected.length,200);assert.equal(selected[0].id,'0')
 for(const size of [25,50,100]) {
   const rows=selectedMaterialPage(selected,2,size)
   assert.equal(rows.length,size);assert.equal(rows[0].number,String(size+1).padStart(3,'0'))
 }
 const removed=selected.filter(lot=>lot.id!=='0')
 assert.equal(selectedMaterialPage(removed,1,25)[0].lot.id,'1')
 assert.equal(orderedMaterials([...removed,lots[0]])[0].id,'0')
 const component=source('features/germination/components/creation/MaterialsStep.vue')
 assert.ok(component.indexOf('selected-material-preview')<component.indexOf('<el-dialog'))
 assert.match(component,/selectionSize = ref\(25\)/);assert.match(component,/未参与实验材料/)
 assert.doesNotMatch(component,/selected-material-collapse/)
})

test('record query changes and clears remain independent of edit validation, including DAG zero',()=>{
 const base={search:'',dag:null,dates:[],materialIds:[],page:1,pageSize:50}
 const edit={root:'',shoot:'',rootNA:false,shootNA:false,measuredAt:'',notes:''}
 const before=structuredClone(edit)
 for(const change of [{search:'001'},{search:''},{materialIds:['a','b']},{materialIds:[]},{dag:3},{dag:''},{dag:undefined},{dag:null},{dates:['2026-09-30','2026-10-07']},{dates:null},{page:2},{pageSize:100}]) {
   assert.doesNotThrow(()=>measurementQueryParams({...base,...change}))
   assert.deepEqual(edit,before)
 }
 for(const value of ['',undefined,null]) assert.equal(measurementQueryParams({...base,dag:value}).has('dag'),false)
 assert.equal(measurementQueryParams({...base,dag:0}).get('dag'),'0')
 assert.equal(normalizedDag(-1),null)
 assert.throws(()=>updateMeasurementPayload(edit),/根长|苗长/)
 const component=source('features/measurement/components/MeasurementRecords.vue')
 assert.doesNotMatch(component,/validate|updateMeasurementPayload|createMeasurementPayload/)
 assert.match(component,/共 {{ total }} 条记录/)
 const editor=source('features/measurement/components/MeasurementEditor.vue')
 assert.ok(editor.indexOf('updateMeasurementPayload(form.value)')>editor.indexOf('async function save()'))
})

test('all/new import handoff uses session storage, rechecks available lots and clears explicitly',()=>{
 const map=new Map(),storage={getItem:key=>map.get(key)||null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)}
 const result={all_seed_lot_ids:['0','1','2','0'],created_seed_lot_ids:['2'],total_material_count:3,existing_material_count:2,created_material_count:1,updated_material_count:0}
 assert.equal(saveMaterialPrefill(storage,result,'all'),true)
 assert.deepEqual(readMaterialPrefill(storage).seed_lot_ids,['0','1','2'])
 assert.ok(readMaterialPrefill(storage).created_at);assert.equal(map.size,1)
 const resolved=resolveMaterialPrefill(readMaterialPrefill(storage),lots.slice(0,2))
 assert.equal(resolved.excluded,1);assert.deepEqual(resolved.lots.map(lot=>lot.id),['0','1'])
 // Reading does not lose a handoff on reload; only completion/explicit exit clears it.
 assert.ok(storage.getItem(MATERIAL_PREFILL_KEY));clearMaterialPrefill(storage);assert.equal(map.size,0)
 saveMaterialPrefill(storage,result,'created');assert.deepEqual(readMaterialPrefill(storage).seed_lot_ids,['2'])
 clearMaterialPrefill(storage);assert.equal(saveMaterialPrefill(storage,{...result,created_seed_lot_ids:[]},'created'),false)
 storage.setItem(MATERIAL_PREFILL_KEY,'bad');assert.equal(readMaterialPrefill(storage),null);assert.equal(map.size,0)
 const wizard=source('features/germination/pages/ExperimentWizardView.vue')
 assert.match(wizard,/onBeforeRouteLeave/);assert.doesNotMatch(wizard,/from_import|localStorage/)
 assert.match(wizard,/clearMaterialPrefill\(sessionStorage\)/)
})

test('workspace has shrinking grids, selected row highlight and collapsed history',()=>{
 const css=source('style.css'),bench=source('features/measurement/components/SeedlingMeasurementWorkbench.vue')
 assert.match(css,/minmax\(0, 1\.2fr\) minmax\(0, 1fr\)/)
 assert.match(css,/@media \(max-width: 1699px\)/)
 assert.match(css,/\.table-subtitle\s*\{\s*display: block/)
 assert.match(bench,/historyOpen = ref\(false\)/);assert.match(bench,/v-if="historyOpen"/)
 assert.match(bench,/当前工作/);assert.match(bench,/row-class-name/)
})

test('data workspace exposes three consistent user workflows and no obsolete import routes',()=>{
 const data=source('views/DataView.vue'),importer=source('views/IntegratedMaterialImport.vue')
 assert.match(data,/导出物种与批次总表/);assert.match(data,/生成实验数据工作簿/)
 assert.doesNotMatch(data,/import\/taxa|import\/seed-lots|单独维护|高级维护/)
 assert.match(importer,/导入种子材料清单/);assert.match(importer,/仅包含新增材料的清单/)
 assert.match(importer,/!imported.created_seed_lot_ids.length/);assert.match(importer,/本次清单没有新增材料/)
})

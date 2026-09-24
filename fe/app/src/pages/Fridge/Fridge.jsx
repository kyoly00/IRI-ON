import { useEffect, useState } from "react";
import { authFetch } from "../../lib/api";
import "./Fridge.css";

const emptyItem = { name: "", ingredient_id: "", quantity: "", unit: "g" };

export default function Fridge() {
  const userId = localStorage.getItem("user_id");
  const [household, setHousehold] = useState(null);
  const [items, setItems] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [requests, setRequests] = useState([]);
  const [newHousehold, setNewHousehold] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [item, setItem] = useState(emptyItem);
  const [visionItems, setVisionItems] = useState([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const requestUrl = (path, init) => authFetch(path, init).then(async (r) => {
    const data = await r.json(); if (!r.ok) throw new Error(data.detail || "요청에 실패했습니다."); return data;
  });
  const load = async () => {
    if (!userId) { setMessage("로그인 후 사용할 수 있습니다."); setLoading(false); return; }
    try {
      const [profile, ingredients] = await Promise.all([requestUrl("/households/me"), requestUrl("/ingredients")]);
      setHousehold(profile.household); setCatalog(ingredients);
      if (profile.household) {
        const [stock, list] = await Promise.all([requestUrl(`/households/${profile.household.household_id}/fridge-items`), requestUrl(`/households/${profile.household.household_id}/purchase-requests`)]);
        setItems(stock); setRequests(list);
      }
    } catch (e) { setMessage(e.message); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const createHousehold = async (e) => { e.preventDefault(); try { await requestUrl("/households", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name:newHousehold}) }); await load(); } catch(e2) { setMessage(e2.message); } };
  const joinHousehold = async (e) => { e.preventDefault(); try { await requestUrl("/households/join", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({invite_code:inviteCode}) }); await load(); } catch(e2) { setMessage(e2.message); } };
  const addItem = async (e) => { e.preventDefault(); try { const payload = { quantity:Number(item.quantity), unit:item.unit }; if (item.ingredient_id) payload.ingredient_id=Number(item.ingredient_id); else payload.name=item.name; await requestUrl(`/households/${household.household_id}/fridge-items`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); setItem(emptyItem); await load(); } catch(e2) { setMessage(e2.message); } };
  const parseImage = async (e) => { const file=e.target.files?.[0]; if(!file) return; const form=new FormData(); form.append("image", file); try { const result=await requestUrl(`/households/${household.household_id}/vision/parse`,{method:"POST",body:form}); setVisionItems(result.items.map((x)=>({...x, quantity:x.quantity || 1, unit:x.unit || "piece"}))); } catch(e2){setMessage(e2.message);} finally {e.target.value="";} };
  const confirmVision = async () => { try { await requestUrl(`/households/${household.household_id}/fridge-items/confirm`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(visionItems.map(({name,quantity,unit})=>({name,quantity:Number(quantity),unit})))}); setVisionItems([]); await load(); } catch(e){setMessage(e.message);} };
  const review = async (id,status) => { try { await requestUrl(`/households/${household.household_id}/purchase-requests/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status})}); await load(); }catch(e){setMessage(e.message);} };
  if (loading) return <main className="shared-fridge"><p>공유 냉장고를 불러오는 중…</p></main>;
  if (!household) return <main className="shared-fridge setup"><h1>우리 집 냉장고</h1><p>부모는 가정을 만들고, 아이는 초대 코드로 참여해요.</p><form onSubmit={createHousehold}><h2>부모 계정</h2><input required value={newHousehold} onChange={(e)=>setNewHousehold(e.target.value)} placeholder="우리 집 이름"/><button>가정 만들기</button></form><form onSubmit={joinHousehold}><h2>아이 계정</h2><input required value={inviteCode} onChange={(e)=>setInviteCode(e.target.value)} placeholder="초대 코드"/><button>초대 코드로 참여</button></form>{message&&<p className="fridge-message">{message}</p>}</main>;
  return <main className="shared-fridge"><header><h1>{household.name} 냉장고</h1><p>{household.role === "parent" ? `부모 계정 · 초대 코드 ${household.invite_code}` : "아이 계정 · 가족과 재료를 함께 관리해요"}</p></header>
    <section className="stock-card"><h2>재료 추가</h2><form className="add-item" onSubmit={addItem}><select value={item.ingredient_id} onChange={(e)=>setItem({...item,ingredient_id:e.target.value,name:""})}><option value="">새 재료 직접 입력</option>{catalog.map((x)=><option value={x.ingredient_id} key={x.ingredient_id}>{x.name}</option>)}</select>{!item.ingredient_id&&<input required value={item.name} onChange={(e)=>setItem({...item,name:e.target.value})} placeholder="재료 이름"/>}<input required type="number" min="0.01" step="0.01" value={item.quantity} onChange={(e)=>setItem({...item,quantity:e.target.value})} placeholder="수량"/><select value={item.unit} onChange={(e)=>setItem({...item,unit:e.target.value})}>{["g","kg","ml","l","cup","tbsp","tsp","piece"].map((u)=><option key={u}>{u}</option>)}</select><button>추가</button></form><label className="upload">영수증 또는 장보기 스크린샷 인식<input type="file" accept="image/*" onChange={parseImage}/></label></section>
    {visionItems.length>0&&<section className="stock-card"><h2>인식 결과 확인</h2>{visionItems.map((x,index)=><div className="vision-row" key={index}><input value={x.name} onChange={(e)=>setVisionItems(visionItems.map((v,i)=>i===index?{...v,name:e.target.value}:v))}/><input type="number" value={x.quantity} onChange={(e)=>setVisionItems(visionItems.map((v,i)=>i===index?{...v,quantity:e.target.value}:v))}/><input value={x.unit} onChange={(e)=>setVisionItems(visionItems.map((v,i)=>i===index?{...v,unit:e.target.value}:v))}/></div>)}<button onClick={confirmVision}>확인 후 냉장고에 추가</button></section>}
    <section className="stock-card"><h2>보유 재료</h2>{items.length ? <div className="fridge-grid">{items.map((x)=><div key={x.fridge_item_id}><strong>{x.name}</strong><span>{x.quantity} {x.unit}</span></div>)}</div> : <p>아직 등록한 재료가 없어요.</p>}</section>
    <section className="stock-card"><h2>{household.role === "parent" ? "구매 요청" : "내 구매 요청"}</h2>{requests.length ? requests.map((request)=><article className="request" key={request.purchase_request_id}><b>{request.recipe_name || "장보기"} · {request.status}</b><p>{request.requester_name} · {request.items.map((x)=>`${x.name} ${x.quantity}${x.unit}`).join(", ")}</p>{household.role==="parent"&&request.status==="pending"&&<><button onClick={()=>review(request.purchase_request_id,"approved")}>승인</button><button onClick={()=>review(request.purchase_request_id,"rejected")}>거절</button></>}{request.status==="approved"&&request.items.map((x)=><a key={x.ingredient_id} href={x.shopping_url} target="_blank" rel="noreferrer">{x.name} 구매 검색</a>)}</article>) : <p>구매 요청이 없습니다.</p>}</section>
    <section className="placeholder-card"><h2>준비 중인 냉장고 기능</h2><p>유통기한 알림 · 조리 후 자동 재고 차감 · 소비 예측 · 냉장고 내부 Vision 인식</p></section>{message&&<p className="fridge-message">{message}</p>}</main>;
}

import streamlit as st
from database import (
    init_db, add_restaurant, get_restaurants, get_restaurant,
    add_dish, add_dishes_bulk, get_dishes, deactivate_dish,
    log_meal, get_history, get_recent_indulgence_score,
    update_restaurant_yelp, CUISINE_CATEGORIES,
)
from recommender import recommend, diet_status_message
from reviews import enrich_restaurant
from config import GOOGLE_PLACES_API_KEY

init_db()

st.set_page_config(page_title="今天吃什么", page_icon="🍜", layout="centered")
st.title("今天吃什么？")

page = st.sidebar.radio(
    "导航",
    ["今天的推荐", "添加餐厅", "导入菜单", "添加菜品", "饮食记录", "管理菜单"],
)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: 今天的推荐
# ─────────────────────────────────────────────────────────────────────────────
if page == "今天的推荐":
    indulgence = get_recent_indulgence_score(days=5)
    st.info(diet_status_message(indulgence))

    # Step 1: cuisine category
    st.subheader("今天想吃什么菜系？")
    # Show only categories that have restaurants
    all_cats = sorted({r["cuisine_category"] for r in get_restaurants() if r["cuisine_category"]})
    if not all_cats:
        all_cats = CUISINE_CATEGORIES
    selected_cats = st.multiselect(
        "选菜系（不选 = 全部）",
        options=all_cats,
        placeholder="随便，全部都行",
    )

    # Step 2: restaurants in those categories
    filtered_rests = get_restaurants(cuisine_categories=selected_cats if selected_cats else None)
    rest_names = {r["name"]: r["id"] for r in filtered_rests}

    if not rest_names:
        st.warning("所选菜系下没有餐厅，先去添加。")
        st.stop()

    st.subheader("今天不想吃什么？")
    col1, col2 = st.columns(2)
    with col1:
        exclude_rests = st.multiselect("排除餐厅", options=list(rest_names.keys()))
    with col2:
        exclude_kws = st.multiselect(
            "排除口味/特征",
            options=["spicy", "salty", "greasy", "oily", "heavy", "sweet", "rich"],
        )

    max_price = st.slider("最高价格 ($)", 0, 60, 30)
    prefer_healthy = st.checkbox("今天想吃健康一点", value=(indulgence >= 0.4))

    if st.button("给我推荐！", type="primary", use_container_width=True):
        exclude_ids = [rest_names[n] for n in exclude_rests]
        results = recommend(
            cuisine_categories=selected_cats if selected_cats else None,
            exclude_restaurant_ids=exclude_ids,
            exclude_keywords=exclude_kws,
            max_price=max_price if max_price > 0 else None,
            prefer_healthy=prefer_healthy,
            top_n=3,
        )

        if not results:
            st.warning("没找到符合条件的菜，放宽一下筛选条件试试。")
        else:
            st.subheader("推荐结果")
            for i, d in enumerate(results):
                with st.container(border=True):
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"### {d['name']}")
                        st.caption(f"📍 {d['restaurant_name']}")
                        price_str = f"${d['price']:.2f}" if d['price'] else "价格未知"
                        health_bar = "🟢" * int(d['health_score']) + "⚪" * (5 - int(d['health_score']))
                        rating_str = f"⭐ {d['yelp_rating']}" if d['yelp_rating'] else "暂无评分"
                        st.markdown(f"{price_str} · {health_bar} 健康分 {d['health_score']}/5 · {rating_str}")
                        if d.get("yelp_mentions"):
                            st.caption(f"评价关键词: {d['yelp_mentions']}")
                        if d.get("notes"):
                            st.caption(f"备注: {d['notes']}")
                    with col_b:
                        if d.get("website"):
                            st.link_button("去点餐", d["website"], use_container_width=True)
                        if st.button("就吃这个", key=f"pick_{i}", use_container_width=True):
                            log_meal(d["id"], indulgent=bool(d["is_indulgent"]))
                            st.success(f"已记录：{d['name']}，好好享用！")
                            st.balloons()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: 添加餐厅
# ─────────────────────────────────────────────────────────────────────────────
elif page == "添加餐厅":
    st.subheader("添加新餐厅")
    with st.form("add_restaurant"):
        name     = st.text_input("餐厅名称 *")
        cuisine  = st.text_input("菜系描述（如 Chinese, Japanese, Mexican…）")
        cuisine_category = st.selectbox("分类", CUISINE_CATEGORIES)
        address  = st.text_input("地址（选填，帮助 Google 搜索更准确）")
        website  = st.text_input("官网 / 点餐链接（选填）")
        fetch_google = st.checkbox("自动从 Google Maps 获取评分和信息", value=bool(GOOGLE_PLACES_API_KEY))
        submitted = st.form_submit_button("添加", type="primary")

    if submitted and name:
        google_data = {}
        if fetch_google and GOOGLE_PLACES_API_KEY:
            with st.spinner("正在查询 Google Maps…"):
                google_data = enrich_restaurant(name, address) or {}
            if google_data:
                st.success(
                    f"Google Maps 找到：{name} · ⭐{google_data['google_rating']} "
                    f"({google_data['google_review_count']}条评价)"
                )
                if google_data.get("keywords"):
                    st.info(f"评价关键词：{', '.join(google_data['keywords'])}")
            else:
                st.warning("Google Maps 未找到该餐厅，已手动保存。")

        rid = add_restaurant(
            name=name,
            cuisine=cuisine or google_data.get("categories", ""),
            cuisine_category=cuisine_category,
            address=address or google_data.get("address", ""),
            website=website or google_data.get("website", ""),
            yelp_id=google_data.get("place_id", ""),
            yelp_rating=google_data.get("google_rating", 0),
            yelp_review_count=google_data.get("google_review_count", 0),
        )
        st.success(f"餐厅已添加（ID: {rid}），可以去添加菜品了。")

    st.divider()
    st.subheader("已有餐厅")
    for r in get_restaurants():
        rating_str = f"⭐{r['yelp_rating']}" if r['yelp_rating'] else "无评分"
        cat = r['cuisine_category'] or r['cuisine'] or '未分类'
        st.markdown(f"**{r['name']}** · {cat} · {rating_str}")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: 导入菜单
# ─────────────────────────────────────────────────────────────────────────────
elif page == "导入菜单":
    st.subheader("导入菜单")
    restaurants = get_restaurants()
    if not restaurants:
        st.warning("请先添加餐厅。")
        st.stop()

    rest_options = {r["name"]: r["id"] for r in restaurants}
    rest_name = st.selectbox("选择这份菜单属于哪家餐厅", list(rest_options.keys()))

    tab_google, tab_search, tab_upload = st.tabs(["Google Photos", "在线搜索", "上传文件"])

    with tab_google:
        st.caption("从 Google Maps 下载餐厅照片，你勾选哪些是菜单图，再识别。")
        google_query = st.text_input("餐厅名称", value=rest_name, key="gp_query")

        if st.button("下载照片", use_container_width=True, key="gp_fetch"):
            from reviews import search_restaurant, get_place_photos
            with st.spinner("搜索餐厅并下载照片…"):
                info = search_restaurant(google_query)
            if not info:
                st.error("Google Maps 找不到这家餐厅。")
            else:
                photos = get_place_photos(info["place_id"], max_photos=10)
                if not photos:
                    st.error("没有找到照片。")
                else:
                    st.session_state["gp_photos"] = photos
                    st.session_state["gp_info"] = info

        if "gp_photos" in st.session_state:
            photos = st.session_state["gp_photos"]
            info = st.session_state["gp_info"]
            st.success(f"下载了 {len(photos)} 张照片，勾选菜单图：")

            selected = []
            cols = st.columns(3)
            for i, photo_bytes in enumerate(photos):
                with cols[i % 3]:
                    st.image(photo_bytes, use_container_width=True)
                    if st.checkbox(f"菜单图 #{i+1}", key=f"gp_sel_{i}"):
                        selected.append(photo_bytes)

            if selected and st.button(
                f"识别选中的 {len(selected)} 张图", type="primary",
                use_container_width=True, key="gp_parse"
            ):
                from menu_parser import parse_menu_from_google_photos
                with st.spinner("识别中…"):
                    try:
                        dishes = parse_menu_from_google_photos(selected)
                        st.session_state["parsed_dishes"] = dishes
                        st.session_state["parsed_rest_name"] = rest_name
                        del st.session_state["gp_photos"]
                        del st.session_state["gp_info"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"识别失败：{e}")

    with tab_search:
        search_query = st.text_input(
            "搜索关键词（默认用餐厅名）",
            value=rest_name,
            placeholder="e.g. Pho Binh Houston menu",
        )
        if st.button("搜索菜单", use_container_width=True):
            from menu_search import search_menu_urls
            with st.spinner("搜索中…"):
                results = search_menu_urls(search_query)
            if results:
                st.session_state["search_results"] = results
            else:
                st.warning("没找到结果，试试修改关键词。")

        if "search_results" in st.session_state:
            results = st.session_state["search_results"]
            st.write("选择一个链接导入：")
            for r in results:
                badge = "📄 PDF" if r["is_pdf"] else "🌐 网页"
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"{badge} **{r['title'][:60]}**  \n`{r['url'][:80]}`")
                with col_b:
                    if st.button("导入", key=f"import_{r['url']}"):
                        from menu_search import parse_menu_from_url
                        with st.spinner("下载并识别菜单…"):
                            try:
                                dishes = parse_menu_from_url(r["url"])
                                st.session_state["parsed_dishes"] = dishes
                                st.session_state["parsed_rest_name"] = rest_name
                                del st.session_state["search_results"]
                                st.rerun()
                            except Exception as e:
                                st.error(f"失败：{e}")

    with tab_upload:
        st.caption("可一次上传多张图片（比如菜单每页截图），或一个 PDF")
        uploaded_files = st.file_uploader(
            "上传菜单图片或 PDF",
            type=["jpg", "jpeg", "png", "pdf"],
            accept_multiple_files=True,
        )
        if uploaded_files:
            # Preview images
            img_files = [f for f in uploaded_files if f.type.startswith("image")]
            if img_files:
                cols = st.columns(min(len(img_files), 3))
                for i, f in enumerate(img_files):
                    with cols[i % 3]:
                        st.image(f, use_container_width=True, caption=f.name)

            if st.button("识别所有图片", type="primary", use_container_width=True):
                from menu_parser import parse_menu, parse_menu_from_google_photos
                import PIL.Image, io
                with st.spinner(f"识别 {len(uploaded_files)} 个文件…"):
                    try:
                        # Collect all images across files
                        all_images_bytes = []
                        for f in uploaded_files:
                            data = f.read()
                            ext = f.name.lower().rsplit(".", 1)[-1]
                            if ext == "pdf":
                                import fitz
                                doc = fitz.open(stream=data, filetype="pdf")
                                for page in doc:
                                    all_images_bytes.append(page.get_pixmap(dpi=150).tobytes("png"))
                            else:
                                all_images_bytes.append(data)
                        dishes = parse_menu_from_google_photos(all_images_bytes)
                        st.session_state["parsed_dishes"] = dishes
                        st.session_state["parsed_rest_name"] = rest_name
                    except Exception as e:
                        st.error(f"识别失败：{e}")

    if "parsed_dishes" in st.session_state and st.session_state.get("parsed_rest_name") == rest_name:
        dishes = st.session_state["parsed_dishes"]
        st.success(f"识别到 {len(dishes)} 道菜，请确认后保存：")

        edited = []
        for i, d in enumerate(dishes):
            with st.expander(f"{d['name']}  {'$'+str(d['price']) if d.get('price') else '价格未知'}", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("菜名", value=d["name"], key=f"name_{i}")
                    price = st.number_input("价格 ($)", value=float(d["price"] or 0), min_value=0.0, step=0.5, key=f"price_{i}")
                    calorie_level = st.select_slider("热量", [1,2,3],
                        format_func=lambda x: {1:"低",2:"中",3:"高"}[x],
                        value=int(d.get("calorie_level",2)), key=f"cal_{i}")
                    sodium_level = st.select_slider("钠含量", [1,2,3],
                        format_func=lambda x: {1:"低",2:"中",3:"高"}[x],
                        value=int(d.get("sodium_level",2)), key=f"sod_{i}")
                with col2:
                    veggie_content = st.select_slider("蔬菜", [1,2,3],
                        format_func=lambda x: {1:"少",2:"有",3:"主"}[x],
                        value=int(d.get("veggie_content",1)), key=f"veg_{i}")
                    protein_type = st.selectbox("蛋白质", ["lean","plant","fatty","other"],
                        format_func=lambda x: {"lean":"瘦肉","plant":"植物","fatty":"肥肉","other":"其他"}[x],
                        index=["lean","plant","fatty","other"].index(d.get("protein_type","other")),
                        key=f"prot_{i}")
                    is_indulgent = st.checkbox("放纵餐", value=bool(d.get("is_indulgent",False)), key=f"ind_{i}")
                    notes = st.text_input("备注", value=d.get("notes",""), key=f"notes_{i}")
                edited.append({
                    "name": name, "price": price or None,
                    "calorie_level": calorie_level, "sodium_level": sodium_level,
                    "veggie_content": veggie_content, "protein_type": protein_type,
                    "is_indulgent": is_indulgent, "notes": notes,
                })

        if st.button("全部保存", type="primary", use_container_width=True):
            rid = rest_options[rest_name]
            add_dishes_bulk(rid, edited)
            del st.session_state["parsed_dishes"]
            st.success(f"已保存 {len(edited)} 道菜！")
            st.balloons()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: 添加菜品
# ─────────────────────────────────────────────────────────────────────────────
elif page == "添加菜品":
    st.subheader("添加菜品")
    restaurants = get_restaurants()
    if not restaurants:
        st.warning("请先添加餐厅。")
        st.stop()

    rest_options = {r["name"]: r["id"] for r in restaurants}

    with st.form("add_dish"):
        rest_name  = st.selectbox("餐厅", list(rest_options.keys()))
        dish_name  = st.text_input("菜名 *")
        price      = st.number_input("价格 ($)", min_value=0.0, max_value=200.0, value=15.0, step=0.5)

        st.markdown("**营养信息**（参考AHA饮食指南）")
        col1, col2 = st.columns(2)
        with col1:
            calorie_level = st.select_slider(
                "热量", options=[1, 2, 3],
                format_func=lambda x: {1: "低 (<400kcal)", 2: "中 (400-700)", 3: "高 (>700)"}[x],
                value=2,
            )
            sodium_level = st.select_slider(
                "钠含量", options=[1, 2, 3],
                format_func=lambda x: {1: "低 (<300mg)", 2: "中 (300-600mg)", 3: "高 (>600mg)"}[x],
                value=2,
            )
        with col2:
            veggie_content = st.select_slider(
                "蔬菜含量", options=[1, 2, 3],
                format_func=lambda x: {1: "无/很少", 2: "有一些", 3: "蔬菜为主"}[x],
                value=1,
            )
            protein_type = st.selectbox(
                "蛋白质类型",
                options=["lean", "plant", "fatty", "other"],
                format_func=lambda x: {
                    "lean": "瘦肉/鸡胸", "plant": "植物蛋白",
                    "fatty": "肥肉/油炸", "other": "其他/无"
                }[x],
            )
        is_indulgent = st.checkbox("这是一道放纵餐（油腻/高热/垃圾食品）")
        notes = st.text_area("备注（可选）", height=60)
        submitted = st.form_submit_button("添加菜品", type="primary")

    if submitted and dish_name:
        rid = rest_options[rest_name]
        did = add_dish(
            restaurant_id=rid,
            name=dish_name,
            price=price,
            calorie_level=calorie_level,
            sodium_level=sodium_level,
            veggie_content=veggie_content,
            protein_type=protein_type,
            is_indulgent=is_indulgent,
            notes=notes,
        )
        from database import compute_health_score
        hs = compute_health_score(calorie_level, sodium_level, veggie_content, protein_type, is_indulgent)
        st.success(f"已添加 **{dish_name}**，健康分：{hs}/5")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: 饮食记录
# ─────────────────────────────────────────────────────────────────────────────
elif page == "饮食记录":
    st.subheader("饮食记录")
    days = st.slider("显示最近 N 天", 7, 90, 14)
    history = get_history(days=days)
    if not history:
        st.info("还没有记录，去推荐页面选一道菜吧。")
    else:
        for h in history:
            indulgent_tag = "🔴 放纵餐" if h["indulgent"] else "🟢 健康餐"
            st.markdown(
                f"**{h['eaten_date']}** · {h['restaurant_name']} · "
                f"{h['dish_name']} · {indulgent_tag}"
            )

    st.divider()
    indulgence = get_recent_indulgence_score(days=5)
    st.metric("最近5天放纵餐比例", f"{indulgence*100:.0f}%")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: 管理菜单
# ─────────────────────────────────────────────────────────────────────────────
elif page == "管理菜单":
    st.subheader("管理菜单")
    restaurants = get_restaurants()
    if not restaurants:
        st.info("还没有餐厅。")
        st.stop()

    rest_filter = st.selectbox("选择餐厅查看菜品", [r["name"] for r in restaurants])
    rid = next(r["id"] for r in restaurants if r["name"] == rest_filter)

    if GOOGLE_PLACES_API_KEY and st.button("刷新 Google 评分"):
        r = get_restaurant(rid)
        with st.spinner("查询 Google Maps…"):
            data = enrich_restaurant(r["name"], r["address"] or "")
        if data:
            update_restaurant_yelp(rid, data["place_id"], data["google_rating"],
                                   data["google_review_count"], data.get("website", ""))
            st.success(f"已更新：⭐{data['google_rating']} ({data['google_review_count']}条评价)")
        else:
            st.warning("Google Maps 未找到。")

    dishes = get_dishes(restaurant_id=rid)
    if not dishes:
        st.info("这家店还没有菜品。")
    else:
        st.caption("勾选想点的菜，最后生成订单；或直接去推荐页让系统帮你选。")
        selected_dish_ids = []
        for d in dishes:
            health_bar = "🟢" * int(d['health_score']) + "⚪" * (5 - int(d['health_score']))
            price_str = f"${d['price']:.2f}" if d['price'] else "?"
            col_check, col_info, col_btn = st.columns([1, 5, 1])
            with col_check:
                checked = st.checkbox("选", key=f"sel_{d['id']}", label_visibility="collapsed")
                if checked:
                    selected_dish_ids.append(d["id"])
            with col_info:
                st.markdown(f"**{d['name']}** · {price_str} · {health_bar}")
            with col_btn:
                if st.button("下架", key=f"del_{d['id']}"):
                    deactivate_dish(d["id"])
                    st.rerun()

        if selected_dish_ids:
            st.divider()
            st.subheader("今日订单")
            selected_dishes = [d for d in dishes if d["id"] in selected_dish_ids]
            total = 0.0
            for d in selected_dishes:
                price_str = f"${d['price']:.2f}" if d['price'] else "价格未知"
                health_bar = "🟢" * int(d['health_score']) + "⚪" * (5 - int(d['health_score']))
                st.markdown(f"- **{d['name']}** · {price_str} · {health_bar}")
                if d['price']:
                    total += d['price']
            if total:
                st.markdown(f"**合计：${total:.2f}**")
            rest = get_restaurant(rid)
            if rest and rest["website"]:
                st.link_button("去餐厅官网点餐", rest["website"], use_container_width=True)
            if st.button("记录已点", type="primary", use_container_width=True):
                for d in selected_dishes:
                    log_meal(d["id"], indulgent=bool(d["is_indulgent"]))
                st.success(f"已记录 {len(selected_dishes)} 道菜！")
                st.balloons()

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: API key status
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    if GOOGLE_PLACES_API_KEY and GOOGLE_PLACES_API_KEY != "paste_your_key_here":
        st.success("Google Maps API: 已连接")
    else:
        st.warning("Google Maps API: 未配置\n在 .env 填入 GOOGLE_PLACES_API_KEY")

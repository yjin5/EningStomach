import streamlit as st
from database import (
    init_db, add_restaurant, get_restaurants, get_restaurant,
    add_dish, add_dishes_bulk, get_dishes, deactivate_dish, toggle_favorite, update_dish_protein_type,
    log_meal, get_history, get_history_by_date, delete_meal, delete_meals_by_date,
    get_recent_indulgence_score, update_restaurant_yelp, update_restaurant_hours,
    today_hours, CUISINE_CATEGORIES,
)
from recommender import (
    recommend, diet_status_message, exercise_hint, calorie_estimate,
    single_exercise_hint, total_exercise_summary,
)
from reviews import enrich_restaurant
from config import GOOGLE_PLACES_API_KEY
from i18n import t

init_db()

st.set_page_config(page_title="Food Picker", page_icon="🍜", layout="centered")

# ─── Language selector (top of sidebar) ──────────────────────────────────────
_lang_choice = st.sidebar.radio(
    "语言 / Language", ["中文", "English"], horizontal=True, label_visibility="collapsed"
)
_lang = "en" if _lang_choice == "English" else "zh"
st.sidebar.divider()

st.title(t("app_title", _lang))

# ─── Navigation ──────────────────────────────────────────────────────────────
_PAGE_KEYS = ["recommend", "add_rest", "import", "add_dish", "log", "manage"]
_t_pages = [t(f"page_{k}", _lang) for k in _PAGE_KEYS]
_page_sel = st.sidebar.radio(t("nav_label", _lang), _t_pages)
_page_key = _PAGE_KEYS[_t_pages.index(_page_sel)]

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Today's Picks / 今天的推荐
# ─────────────────────────────────────────────────────────────────────────────
if _page_key == "recommend":
    indulgence = get_recent_indulgence_score(days=5)
    st.info(diet_status_message(indulgence, _lang))

    st.subheader(t("cuisine_header", _lang))
    all_cats = sorted({r["cuisine_category"] for r in get_restaurants() if r["cuisine_category"]})
    if not all_cats:
        all_cats = CUISINE_CATEGORIES
    selected_cats = st.multiselect(
        t("cuisine_select", _lang),
        options=all_cats,
        placeholder=t("cuisine_placeholder", _lang),
    )

    filtered_rests = get_restaurants(cuisine_categories=selected_cats if selected_cats else None)
    rest_names = {r["name"]: r["id"] for r in filtered_rests}

    if not rest_names:
        st.warning(t("no_rest_warning", _lang))
        st.stop()

    st.subheader(t("avoid_header", _lang))
    col1, col2 = st.columns(2)
    with col1:
        exclude_rests = st.multiselect(t("exclude_rest", _lang), options=list(rest_names.keys()))
    with col2:
        exclude_kws = st.multiselect(
            t("exclude_flavor", _lang),
            options=["spicy", "salty", "greasy", "oily", "heavy", "sweet", "rich"],
        )

    max_price  = st.slider(t("max_price", _lang), 0, 100, 30)
    min_rating = st.slider(t("min_rating", _lang), 0.0, 5.0, 0.0, step=0.5)
    col_h, col_f = st.columns(2)
    with col_h:
        prefer_healthy = st.checkbox(t("prefer_healthy", _lang), value=(indulgence >= 0.4))
    with col_f:
        boost_favorites = st.checkbox(t("favorites_first", _lang))

    _MEAT_OPTIONS = {
        "poultry": t("poultry", _lang),
        "seafood": t("seafood", _lang),
        "beef":    t("beef",    _lang),
        "pork":    t("pork",    _lang),
        "lamb":    t("lamb",    _lang),
    }
    required_meats = st.multiselect(
        t("meat_select", _lang),
        options=list(_MEAT_OPTIONS.keys()),
        format_func=lambda x: _MEAT_OPTIONS[x],
        placeholder=t("meat_placeholder", _lang),
    )

    if st.button(t("recommend_btn", _lang), type="primary", use_container_width=True):
        exclude_ids = [rest_names[n] for n in exclude_rests]

        shown = st.session_state.get("shown_dish_ids", set())
        _rec_kwargs = dict(
            cuisine_categories=selected_cats if selected_cats else None,
            exclude_restaurant_ids=exclude_ids,
            exclude_keywords=exclude_kws,
            max_price=max_price if max_price > 0 else None,
            prefer_healthy=prefer_healthy,
            top_n=3,
            required_protein_types=required_meats if required_meats else None,
            min_rating=min_rating if min_rating > 0 else 0.0,
            boost_favorites=boost_favorites,
        )
        results = recommend(**_rec_kwargs, exclude_shown_ids=shown)
        if not results:
            shown = set()
            st.session_state["shown_dish_ids"] = set()
            results = recommend(**_rec_kwargs)

        if not results:
            st.warning(t("no_results", _lang))
        else:
            st.session_state["shown_dish_ids"] = shown | {d["id"] for d in results}

            st.subheader(t("results_header", _lang))
            for i, d in enumerate(results):
                with st.container(border=True):
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"### {d['name']}")
                        st.caption(f"📍 {d['restaurant_name']}")
                        price_str = f"${d['price']:.2f}" if d['price'] else t("price_unknown", _lang)
                        health_bar = "🟢" * int(d['health_score']) + "⚪" * (5 - int(d['health_score']))
                        rating_str = f"⭐ {d['yelp_rating']}" if d['yelp_rating'] else t("no_rating", _lang)
                        st.markdown(f"{price_str} · {health_bar} {t('health_label', _lang)} {d['health_score']}/5 · {rating_str}")
                        st.caption(exercise_hint(d.get("calorie_level", 2), _lang))
                        if d.get("yelp_mentions"):
                            st.caption(f"{t('review_kw', _lang)}: {d['yelp_mentions']}")
                        if d.get("notes"):
                            st.caption(f"{t('notes_label', _lang)}: {d['notes']}")
                    with col_b:
                        if d.get("website"):
                            st.link_button(t("order_btn", _lang), d["website"], use_container_width=True)
                        if st.button(t("pick_btn", _lang), key=f"pick_{i}", use_container_width=True):
                            log_meal(d["id"], indulgent=bool(d["is_indulgent"]))
                            st.session_state["shown_dish_ids"] = set()
                            st.success(t("logged_msg", _lang, name=d['name']))
                            st.balloons()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Add Restaurant / 添加餐厅
# ─────────────────────────────────────────────────────────────────────────────
elif _page_key == "add_rest":
    st.subheader(t("add_rest_header", _lang))
    with st.form("add_restaurant"):
        name             = st.text_input(t("rest_name", _lang))
        cuisine          = st.text_input(t("cuisine_desc", _lang))
        cuisine_category = st.selectbox(t("category", _lang), CUISINE_CATEGORIES)
        address          = st.text_input(t("address", _lang))
        website          = st.text_input(t("website", _lang))
        fetch_google     = st.checkbox(t("fetch_google", _lang), value=bool(GOOGLE_PLACES_API_KEY))
        submitted        = st.form_submit_button(t("add_btn", _lang), type="primary")

    if submitted and name:
        google_data = {}
        if fetch_google and GOOGLE_PLACES_API_KEY:
            with st.spinner(t("google_spinner", _lang)):
                google_data = enrich_restaurant(name, address) or {}
            if google_data:
                st.success(t("google_found", _lang,
                             name=name,
                             rating=google_data["google_rating"],
                             count=google_data["google_review_count"]))
                if google_data.get("keywords"):
                    st.info(f"{t('review_kw_label', _lang)}{', '.join(google_data['keywords'])}")
            else:
                st.warning(t("google_not_found", _lang))

        import json as _json
        hours_list = google_data.get("opening_hours")
        rid = add_restaurant(
            name=name,
            cuisine=cuisine or google_data.get("categories", ""),
            cuisine_category=cuisine_category,
            address=address or google_data.get("address", ""),
            website=website or google_data.get("website", ""),
            yelp_id=google_data.get("place_id", ""),
            yelp_rating=google_data.get("google_rating", 0),
            yelp_review_count=google_data.get("google_review_count", 0),
            opening_hours=_json.dumps(hours_list) if hours_list else None,
        )
        st.success(t("rest_added", _lang, id=rid))

    st.divider()
    st.subheader(t("existing_rests", _lang))
    for r in get_restaurants():
        rating_str = f"⭐{r['yelp_rating']}" if r['yelp_rating'] else t("no_rating_short", _lang)
        cat = r['cuisine_category'] or r['cuisine'] or t("uncategorized", _lang)
        st.markdown(f"**{r['name']}** · {cat} · {rating_str}")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Import Menu / 导入菜单
# ─────────────────────────────────────────────────────────────────────────────
elif _page_key == "import":
    st.subheader(t("import_header", _lang))
    restaurants = get_restaurants()
    if not restaurants:
        st.warning(t("no_rest_first", _lang))
        st.stop()

    rest_options = {r["name"]: r["id"] for r in restaurants}
    rest_name = st.selectbox(t("select_rest", _lang), list(rest_options.keys()))

    tab_google, tab_search, tab_upload = st.tabs(
        ["Google Photos", t("tab_online", _lang), t("tab_upload", _lang)]
    )

    with tab_google:
        st.caption(t("gp_caption", _lang))
        google_query = st.text_input(t("rest_name_label", _lang), value=rest_name, key="gp_query")

        if st.button(t("download_photos", _lang), use_container_width=True, key="gp_fetch"):
            from reviews import search_restaurant, get_place_photos, is_menu_photo
            with st.spinner(t("gp_spinner", _lang)):
                info = search_restaurant(google_query)
            if not info:
                st.error(t("gp_not_found", _lang))
            else:
                photos = get_place_photos(info["place_id"], max_photos=10)
                if not photos:
                    st.error(t("no_photos", _lang))
                else:
                    with st.spinner(t("detect_spinner", _lang, n=len(photos))):
                        flags = [is_menu_photo(p) for p in photos]
                    st.session_state["gp_photos"] = photos
                    st.session_state["gp_flags"]  = flags
                    st.session_state["gp_info"]   = info

        if "gp_photos" in st.session_state:
            photos     = st.session_state["gp_photos"]
            flags      = st.session_state.get("gp_flags", [False] * len(photos))
            menu_count = sum(flags)
            st.success(t("gp_found", _lang, total=len(photos), menus=menu_count))

            selected = []
            cols = st.columns(3)
            for i, photo_bytes in enumerate(photos):
                with cols[i % 3]:
                    label = t("is_menu", _lang) if flags[i] else t("not_menu", _lang)
                    st.image(photo_bytes, use_container_width=True, caption=label)
                    if st.checkbox(t("pick_photo", _lang, n=i + 1), key=f"gp_sel_{i}", value=flags[i]):
                        selected.append(photo_bytes)

            if selected and st.button(
                t("parse_selected", _lang, n=len(selected)),
                type="primary", use_container_width=True, key="gp_parse",
            ):
                from menu_parser import parse_menu_from_google_photos
                with st.spinner(t("parsing", _lang)):
                    try:
                        dishes = parse_menu_from_google_photos(selected)
                        st.session_state["parsed_dishes"]    = dishes
                        st.session_state["parsed_rest_name"] = rest_name
                        del st.session_state["gp_photos"]
                        del st.session_state["gp_info"]
                        st.session_state.pop("gp_flags", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"{t('parse_failed', _lang)}{e}")

    with tab_search:
        search_query = st.text_input(
            t("search_kw", _lang),
            value=rest_name,
            placeholder="e.g. Pho Binh Houston menu",
        )
        if st.button(t("search_btn", _lang), use_container_width=True):
            from menu_search import search_menu_urls
            with st.spinner(t("searching", _lang)):
                results = search_menu_urls(search_query)
            if results:
                st.session_state["search_results"] = results
            else:
                st.warning(t("no_search_result", _lang))

        if "search_results" in st.session_state:
            results = st.session_state["search_results"]
            st.write(t("pick_link", _lang))
            for r in results:
                badge = "📄 PDF" if r["is_pdf"] else "🌐"
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"{badge} **{r['title'][:60]}**  \n`{r['url'][:80]}`")
                with col_b:
                    if st.button(t("import_btn", _lang), key=f"import_{r['url']}"):
                        from menu_search import parse_menu_from_url
                        with st.spinner(t("dl_parse_spinner", _lang)):
                            try:
                                dishes = parse_menu_from_url(r["url"])
                                st.session_state["parsed_dishes"]    = dishes
                                st.session_state["parsed_rest_name"] = rest_name
                                del st.session_state["search_results"]
                                st.rerun()
                            except Exception as e:
                                st.error(f"{t('import_failed', _lang)}{e}")

    with tab_upload:
        st.caption(t("upload_caption", _lang))
        uploaded_files = st.file_uploader(
            t("upload_label", _lang),
            type=["jpg", "jpeg", "png", "pdf"],
            accept_multiple_files=True,
        )
        if uploaded_files:
            img_files = [f for f in uploaded_files if f.type.startswith("image")]
            if img_files:
                cols = st.columns(min(len(img_files), 3))
                for i, f in enumerate(img_files):
                    with cols[i % 3]:
                        st.image(f, use_container_width=True, caption=f.name)

            if st.button(t("parse_all_btn", _lang), type="primary", use_container_width=True):
                from menu_parser import parse_menu_from_google_photos
                with st.spinner(t("parsing_n", _lang, n=len(uploaded_files))):
                    try:
                        all_images_bytes = []
                        for f in uploaded_files:
                            data = f.read()
                            ext  = f.name.lower().rsplit(".", 1)[-1]
                            if ext == "pdf":
                                import fitz
                                doc = fitz.open(stream=data, filetype="pdf")
                                for page in doc:
                                    all_images_bytes.append(page.get_pixmap(dpi=150).tobytes("png"))
                            else:
                                all_images_bytes.append(data)
                        dishes = parse_menu_from_google_photos(all_images_bytes)
                        st.session_state["parsed_dishes"]    = dishes
                        st.session_state["parsed_rest_name"] = rest_name
                    except Exception as e:
                        st.error(f"{t('parse_failed', _lang)}{e}")

    if "parsed_dishes" in st.session_state and st.session_state.get("parsed_rest_name") == rest_name:
        dishes = st.session_state["parsed_dishes"]
        st.success(t("found_dishes", _lang, n=len(dishes)))

        _cal_labels = {x: t(f"cal_{x}", _lang) for x in [0, 1, 2, 3]}
        _sod_labels = {x: t(f"sod_{x}", _lang) for x in [1, 2, 3]}
        _veg_labels = {x: t(f"veg_{x}", _lang) for x in [1, 2, 3]}
        _PTYPES = ["poultry", "seafood", "beef", "pork", "lamb", "plant", "other"]
        _PNAMES = {k: t(k, _lang) for k in _PTYPES}

        edited = []
        for i, d in enumerate(dishes):
            price_disp = f"${d['price']}" if d.get("price") else t("price_unknown", _lang)
            with st.expander(f"{d['name']}  {price_disp}", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    name          = st.text_input(t("dish_name", _lang), value=d["name"], key=f"name_{i}")
                    price         = st.number_input(t("price", _lang), value=float(d["price"] or 0), min_value=0.0, step=0.5, key=f"price_{i}")
                    calorie_level = st.select_slider(t("calorie", _lang), [0, 1, 2, 3],
                                       format_func=lambda x: _cal_labels[x],
                                       value=int(d.get("calorie_level", 2)), key=f"cal_{i}")
                    sodium_level  = st.select_slider(t("sodium", _lang), [1, 2, 3],
                                       format_func=lambda x: _sod_labels[x],
                                       value=int(d.get("sodium_level", 2)), key=f"sod_{i}")
                with col2:
                    veggie_content = st.select_slider(t("veggie", _lang), [1, 2, 3],
                                        format_func=lambda x: _veg_labels[x],
                                        value=int(d.get("veggie_content", 1)), key=f"veg_{i}")
                    _pt_val = d.get("protein_type", "other")
                    if _pt_val not in _PTYPES:
                        _pt_val = "other"
                    protein_type = st.selectbox(t("protein", _lang), _PTYPES,
                                      format_func=lambda x: _PNAMES[x],
                                      index=_PTYPES.index(_pt_val), key=f"prot_{i}")
                    is_indulgent = st.checkbox(t("indulgent", _lang), value=bool(d.get("is_indulgent", False)), key=f"ind_{i}")
                    notes        = st.text_input(t("notes", _lang), value=d.get("notes", ""), key=f"notes_{i}")
                edited.append({
                    "name": name, "price": price or None,
                    "calorie_level": calorie_level, "sodium_level": sodium_level,
                    "veggie_content": veggie_content, "protein_type": protein_type,
                    "is_indulgent": is_indulgent, "notes": notes,
                })

        if st.button(t("save_all", _lang), type="primary", use_container_width=True):
            rid = rest_options[rest_name]
            add_dishes_bulk(rid, edited)
            del st.session_state["parsed_dishes"]
            st.success(t("saved_n", _lang, n=len(edited)))
            st.balloons()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Add Dish / 添加菜品
# ─────────────────────────────────────────────────────────────────────────────
elif _page_key == "add_dish":
    st.subheader(t("add_dish_header", _lang))
    restaurants = get_restaurants()
    if not restaurants:
        st.warning(t("no_rest_first", _lang))
        st.stop()

    rest_options = {r["name"]: r["id"] for r in restaurants}

    with st.form("add_dish"):
        rest_name = st.selectbox(t("restaurant", _lang), list(rest_options.keys()))
        dish_name = st.text_input(t("dish_name_req", _lang))
        price     = st.number_input(t("price", _lang), min_value=0.0, max_value=200.0, value=15.0, step=0.5)

        st.markdown(f"**{t('nutrition_header', _lang)}**")
        col1, col2 = st.columns(2)
        with col1:
            calorie_level = st.select_slider(
                t("calorie", _lang), options=[0, 1, 2, 3],
                format_func=lambda x: t(f"cal_full_{x}", _lang),
                value=2,
            )
            sodium_level = st.select_slider(
                t("sodium", _lang), options=[1, 2, 3],
                format_func=lambda x: t(f"sod_full_{x}", _lang),
                value=2,
            )
        with col2:
            veggie_content = st.select_slider(
                t("veggie", _lang), options=[1, 2, 3],
                format_func=lambda x: t(f"veg_full_{x}", _lang),
                value=1,
            )
            protein_type = st.selectbox(
                t("protein_type", _lang),
                options=["poultry", "seafood", "beef", "pork", "lamb", "plant", "other"],
                format_func=lambda x: t(f"{x}_full", _lang),
            )
        is_indulgent = st.checkbox(t("indulgent_desc", _lang))
        notes        = st.text_area(t("notes_opt", _lang), height=60)
        submitted    = st.form_submit_button(t("add_dish_btn", _lang), type="primary")

    if submitted and dish_name:
        rid = rest_options[rest_name]
        add_dish(
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
        st.success(t("dish_added", _lang, name=dish_name, score=hs))

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Food Log / 饮食记录
# ─────────────────────────────────────────────────────────────────────────────
elif _page_key == "log":
    st.subheader(t("log_header", _lang))
    days = st.slider(t("show_days", _lang), 7, 90, 14)
    history = get_history(days=days)
    if not history:
        st.info(t("no_log", _lang))
    else:
        for h in history:
            tag = f"🔴 {t('indulgent_tag', _lang)}" if h["indulgent"] else f"🟢 {t('healthy_tag', _lang)}"
            st.markdown(
                f"**{h['eaten_date']}** · {h['restaurant_name']} · {h['dish_name']} · {tag}"
            )

    st.divider()
    indulgence = get_recent_indulgence_score(days=5)
    st.metric(t("indulgent_ratio", _lang), f"{indulgence * 100:.0f}%")

    st.divider()
    st.subheader(t("delete_by_date", _lang))
    import datetime
    del_date     = st.date_input(t("select_date", _lang), value=datetime.date.today(), key="del_date")
    del_date_str = str(del_date)
    day_records  = get_history_by_date(del_date_str)
    if not day_records:
        st.caption(t("no_records_date", _lang, date=del_date_str))
    else:
        st.caption(t("records_on_date", _lang, date=del_date_str, n=len(day_records)))
        for h in day_records:
            tag = t("indulgent_tag", _lang) if h["indulgent"] else t("healthy_tag", _lang)
            col_text, col_btn = st.columns([5, 1])
            with col_text:
                st.markdown(f"{h['restaurant_name']} · {h['dish_name']} · {tag}")
            with col_btn:
                if st.button(t("delete_btn", _lang), key=f"delmeal_{h['id']}"):
                    delete_meal(h["id"])
                    st.rerun()
        st.divider()
        if st.button(t("delete_all_date", _lang, date=del_date_str), type="primary", use_container_width=True):
            delete_meals_by_date(del_date_str)
            st.success(t("deleted_date", _lang, date=del_date_str))
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE: Manage Menu / 管理菜单
# ─────────────────────────────────────────────────────────────────────────────
elif _page_key == "manage":
    st.subheader(t("manage_header", _lang))
    restaurants = get_restaurants()
    if not restaurants:
        st.info(t("no_rests", _lang))
        st.stop()

    rest_filter = st.selectbox(t("select_rest_view", _lang), [r["name"] for r in restaurants])
    rid      = next(r["id"] for r in restaurants if r["name"] == rest_filter)
    rest_row = next(r for r in restaurants if r["name"] == rest_filter)
    hours_str = today_hours(rest_row.get("opening_hours"))
    if hours_str:
        if "Closed" in hours_str:
            st.warning(t("closed_today", _lang, hours=hours_str))
        else:
            st.caption(t("hours_today", _lang, hours=hours_str))

    if GOOGLE_PLACES_API_KEY and st.button(t("refresh_google", _lang)):
        r = get_restaurant(rid)
        with st.spinner(t("google_query_spinner", _lang)):
            data = enrich_restaurant(r["name"], r["address"] or "")
        if data:
            import json as _json
            update_restaurant_yelp(rid, data["place_id"], data["google_rating"],
                                   data["google_review_count"], data.get("website", ""))
            if data.get("opening_hours"):
                update_restaurant_hours(rid, _json.dumps(data["opening_hours"]))
            st.success(t("google_updated", _lang, rating=data["google_rating"], count=data["google_review_count"]))
        else:
            st.warning(t("google_not_found2", _lang))

    dishes = get_dishes(restaurant_id=rid)
    if not dishes:
        st.info(t("no_dishes", _lang))
    else:
        col_caption, col_clear = st.columns([4, 1])
        with col_caption:
            st.caption(t("manage_caption", _lang))
        with col_clear:
            if st.button(t("deselect_all", _lang), key="clear_all"):
                for d in dishes:
                    st.session_state[f"sel_{d['id']}"] = False
                st.rerun()

        _PT_OPTS   = ["poultry", "seafood", "beef", "pork", "lamb", "plant", "other", "lean", "fatty"]
        _PT_LABELS = {k: t(k, _lang) for k in _PT_OPTS}

        selected_dish_ids = []
        for d in dishes:
            health_bar = "🟢" * int(d["health_score"]) + "⚪" * (5 - int(d["health_score"]))
            price_str  = f"${d['price']:.2f}" if d["price"] else "?"
            col_check, col_info, col_fav, col_btn = st.columns([1, 5, 1, 1])
            with col_check:
                checked = st.checkbox("sel", key=f"sel_{d['id']}", label_visibility="collapsed")
                if checked:
                    selected_dish_ids.append(d["id"])
            with col_info:
                kcal              = calorie_estimate(d.get("calorie_level", 2))
                ex_name, ex_mins  = single_exercise_hint(d.get("calorie_level", 2), _lang)
                st.markdown(f"**{d['name']}** · {price_str} · {health_bar}")
                cur_pt = d.get("protein_type", "other")
                if cur_pt not in _PT_OPTS:
                    cur_pt = "other"
                new_pt = st.selectbox(
                    "pt",
                    options=_PT_OPTS,
                    format_func=lambda x: _PT_LABELS[x],
                    index=_PT_OPTS.index(cur_pt),
                    key=f"pt_{d['id']}",
                    label_visibility="collapsed",
                )
                if new_pt != cur_pt:
                    update_dish_protein_type(d["id"], new_pt)
                    st.rerun()
                st.caption(t("kcal_hint", _lang, kcal=kcal, ex=ex_name, mins=ex_mins))
            with col_fav:
                is_fav = bool(d.get("is_favorite"))
                if st.button("★" if is_fav else "☆", key=f"fav_{d['id']}"):
                    toggle_favorite(d["id"], not is_fav)
                    st.rerun()
            with col_btn:
                if st.button(t("remove_btn", _lang), key=f"del_{d['id']}"):
                    deactivate_dish(d["id"])
                    st.rerun()

        if selected_dish_ids:
            st.divider()
            st.subheader(t("order_header", _lang))
            selected_dishes = [d for d in dishes if d["id"] in selected_dish_ids]
            total = 0.0
            for d in selected_dishes:
                price_str  = f"${d['price']:.2f}" if d["price"] else t("price_unknown", _lang)
                health_bar = "🟢" * int(d["health_score"]) + "⚪" * (5 - int(d["health_score"]))
                st.markdown(f"- **{d['name']}** · {price_str} · {health_bar}")
                if d["price"]:
                    total += d["price"]
            if total:
                st.markdown(f"**{t('total', _lang, total=total)}**")
            total_kcal = sum(calorie_estimate(d.get("calorie_level", 2)) for d in selected_dishes)
            st.info(total_exercise_summary(total_kcal, _lang))
            rest = get_restaurant(rid)
            if rest and rest["website"]:
                st.link_button(t("order_website", _lang), rest["website"], use_container_width=True)
            if st.button(t("log_order_btn", _lang), type="primary", use_container_width=True):
                for d in selected_dishes:
                    log_meal(d["id"], indulgent=bool(d["is_indulgent"]))
                st.success(t("order_logged", _lang, n=len(selected_dishes)))
                st.balloons()

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: API key status
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    if GOOGLE_PLACES_API_KEY and GOOGLE_PLACES_API_KEY != "paste_your_key_here":
        st.success(t("api_ok", _lang))
    else:
        st.warning(t("api_missing", _lang))

-- Included inside the cockpit CLIENT block; render targets are reused by the local pilot.
    local display_rendering = false
    local display_data = {}
    local mirror_material = CreateMaterial("wt_cockpit_mirror_cubemap", "VertexLitGeneric", {
        ["$basetexture"] = "models/debug/debugwhite", ["$color2"] = "[0.015 0.015 0.015]",
        ["$envmap"] = "env_cubemap", ["$envmaptint"] = "[0.9 0.9 0.9]"
    })
    local display_green = Color(90, 255, 130)
    local instrument_faces = {}
    for _, name in ipairs({"mfd_speed", "mfd_altitude", "mfd_vario", "mfd_horizont_mask"}) do
        instrument_faces[name] = Material("wt_cockpit/instruments/" .. name .. ".png", "smooth")
    end

    local function instrument_face(name, x, y, size)
        surface.SetMaterial(instrument_faces[name])
        surface.SetDrawColor(255, 255, 255)
        surface.DrawTexturedRect(x, y, size, size)
    end

    local function instrument_needle(x, y, length, angle)
        local c, s = math.cos(angle), math.sin(angle)
        surface.SetDrawColor(255, 255, 255)
        surface.DrawLine(x, y, x - length * c, y - length * s)
        draw.NoTexture()
        surface.DrawPoly({
            {x = x - length * c, y = y - length * s},
            {x = x - length * 0.82 * c + 3 * s, y = y - length * 0.82 * s - 3 * c},
            {x = x - length * 0.82 * c - 3 * s, y = y - length * 0.82 * s + 3 * c}
        })
    end

    -- Native drawSu30SpeedDevice piecewise dial scale (m/s -> radians).
    local function speed_angle(speed)
        local points = {{0, 0.5}, {55.55, 0.69}, {111.11, 1.165}, {166.67, 1.5}, {277.78, 2}, {416.67, 2.5}}
        speed = math.Clamp(speed, 0, points[#points][1])
        for index = 2, #points do
            local a, b = points[index - 1], points[index]
            if speed <= b[1] then return math.pi * Lerp((speed - a[1]) / (b[1] - a[1]), a[2], b[2]) end
        end
    end
    surface.CreateFont("WTGlide.MFD", {font = "Arial", size = 25, weight = 600, extended = true})

    for index, data in ipairs(surfaces.displays or {}) do
        local u0, v0, u1, v1 = math.huge, math.huge, -math.huge, -math.huge
        local center, count = Vector(), 0
        for _, triangle in ipairs(data.triangles) do
            for _, vertex in ipairs(triangle) do
                u0, v0 = math.min(u0, vertex[4]), math.min(v0, vertex[5])
                u1, v1 = math.max(u1, vertex[4]), math.max(v1, vertex[5])
                center = center + Vector(vertex[1], vertex[2], vertex[3])
                count = count + 1
            end
        end
        if data.material ~= "dynamic_mirror" and count > 0 and u1 > u0 and v1 > v0 then
            data.center = center / count
            data.uv = {u0, v0, u1 - u0, v1 - v0}
            data.rt = GetRenderTarget("wt_cockpit_display_" .. index, 512, 512)
            data.material_rt = CreateMaterial("wt_cockpit_display_" .. index, "UnlitGeneric", {
                ["$basetexture"] = data.rt:GetName(), ["$model"] = "1"
            })
            display_data[#display_data + 1] = data
        end
    end

    local function mfd_text(text, x, y, align)
        draw.SimpleText(text, "WTGlide.MFD", x, y, display_green, align or TEXT_ALIGN_LEFT, TEXT_ALIGN_TOP)
    end

    local function draw_mfd(vehicle, data)
        local angles = vehicle:GetAngles()
        local velocity = vehicle:GetVelocity()
        if data.name == "cn_gauge_mfi_j_16" then
            -- Native mfdSu35J16Horizon: cyan/red horizon, 5-degree ladder, rotating aircraft.
            local pitch, heading = -math.NormalizeAngle(angles.p), (-angles.y) % 360
            mfd_text(string.format("%03d", heading), 256, 8, TEXT_ALIGN_CENTER)
            for offset = -60, 60, 10 do
                local x = 256 + offset * 3
                surface.SetDrawColor(display_green)
                surface.DrawLine(x, 40, x, offset % 30 == 0 and 54 or 47)
            end
            local cx, cy, radius = 256, 180, 108
            local horizon = cy + pitch * (radius * 2 / 60)
            -- Circular viewport avoids another texture/RT and keeps the native mask silhouette.
            for y = -radius, radius do
                local half = math.sqrt(radius * radius - y * y)
                if cy + y < horizon then surface.SetDrawColor(0, 200, 204)
                else surface.SetDrawColor(170, 36, 24) end
                surface.DrawLine(cx - half, cy + y, cx + half, cy + y)
            end
            for mark = -90, 90, 5 do
                local y = cy + (pitch - mark) * (radius * 2 / 60)
                if math.abs(y - cy) < radius - 12 then
                    local width = mark == 0 and 96 or (mark % 10 == 0 and 36 or 12)
                    surface.SetDrawColor(255, 255, 255)
                    surface.DrawLine(cx - width, y, cx - 9, y)
                    surface.DrawLine(cx + 9, y, cx + width, y)
                    if mark ~= 0 and mark % 10 == 0 then
                        draw.SimpleText(tostring(math.abs(mark)), "WTGlide.MFD", cx, y, color_white, TEXT_ALIGN_CENTER, TEXT_ALIGN_CENTER)
                    end
                end
            end
            local roll = math.rad(angles.r)
            local function symbol_line(x1, y1, x2, y2)
                local c, s = math.cos(roll), math.sin(roll)
                surface.DrawLine(cx + x1 * c - y1 * s, cy + x1 * s + y1 * c,
                    cx + x2 * c - y2 * s, cy + x2 * s + y2 * c)
            end
            surface.SetDrawColor(0, 0, 0)
            symbol_line(-100, 0, -25, 0)
            symbol_line(-25, 0, -18, 10)
            symbol_line(-18, 10, -10, 0)
            symbol_line(100, 0, 25, 0)
            symbol_line(25, 0, 18, 10)
            symbol_line(18, 10, 10, 0)
            symbol_line(0, -12, 0, -30)
            for bank = -60, 60, 10 do
                local a = math.rad(bank - 90)
                surface.SetDrawColor(255, 255, 255)
                surface.DrawLine(cx + math.cos(a) * 114, cy + math.sin(a) * 114,
                    cx + math.cos(a) * 122, cy + math.sin(a) * 122)
            end
            instrument_face("mfd_horizont_mask", cx - radius, cy - radius, radius * 2)
            -- Native faces/scales; Source speed and world Z are NOT IAS/barometric altitude.
            local speed, altitude, climb = velocity:Length() * 0.0254, vehicle:GetPos().z * 0.0254, velocity.z * 0.0254
            instrument_face("mfd_speed", 20, 315, 176)
            instrument_face("mfd_altitude", 316, 315, 176)
            instrument_needle(108, 403, 79, speed_angle(speed))
            if altitude >= 0 then
                instrument_needle(404, 403, 53, math.pi * (0.5 + altitude / 5000))
                instrument_needle(404, 403, 79, math.pi * (0.5 + (altitude % 1000) / 500))
            end
            mfd_text("SPD km/h", 108, 288, TEXT_ALIGN_CENTER)
            mfd_text("MAP Z m", 404, 288, TEXT_ALIGN_CENTER)
            mfd_text(string.format("%.0f", speed * 3.6), 108, 422, TEXT_ALIGN_CENTER)
            mfd_text(string.format("%.0f", altitude), 404, 422, TEXT_ALIGN_CENTER)
            instrument_face("mfd_vario", 206, 330, 100)
            local rate = math.abs(climb)
            local angle = rate < 10 and rate / 10 * 0.25 or (rate < 20 and 0.25 + (rate - 10) / 10 * 0.15 or 0.4 + math.min(rate - 20, 10) / 10 * 0.08)
            instrument_needle(256, 380, 45, math.pi * angle * (climb < 0 and -1 or 1))
            mfd_text("V/S", 256, 438, TEXT_ALIGN_CENTER)
            mfd_text(string.format("%+.1f", climb), 256, 466, TEXT_ALIGN_CENTER)
        elseif data.name == "cn_gauge_mfi_j_16_1" then
            mfd_text("WEAPON STATUS", 256, 18, TEXT_ALIGN_CENTER)
            local weapon = vehicle.weapons and vehicle.weapons[vehicle.weaponSlotIndex]
            local info = vehicle.WeaponInfo and vehicle.WeaponInfo[vehicle.weaponSlotIndex]
            if weapon then
                mfd_text(info and info.name or weapon.Name or weapon.ClassName, 20, 110)
                mfd_text("AMMO  " .. tostring(weapon.ammo or 0), 20, 170)
                mfd_text(string.format("RELOAD  %d%%", (weapon.reloadProgress or 0) * 100), 20, 215)
            else
                mfd_text("NO ACTIVE WEAPON", 20, 110)
            end
            mfd_text("LOCK  " .. tostring(vehicle:GetLockOnState()), 20, 285)
            mfd_text("RADAR / RWR: NO DATA", 20, 440)
        else
            mfd_text("FLIGHT DATA", 256, 18, TEXT_ALIGN_CENTER)
            mfd_text(string.format("SPD  %d km/h", velocity:Length() * 0.0254 * 3.6), 25, 120)
            mfd_text(string.format("MAP Z  %d m", vehicle:GetPos().z * 0.0254), 25, 180)
            mfd_text(string.format("V/S  %+.1f m/s", velocity.z * 0.0254), 25, 240)
            mfd_text(string.format("HDG  %03d", (-angles.y) % 360), 25, 300)
            mfd_text("MAP HEIGHT / NOT BARO ALT", 25, 440)
        end
    end

    local next_display_update = 0
    hook.Add("PostRender", "WTGlide.CockpitDisplays", function()
        if display_rendering or RealTime() < next_display_update then return end
        local vehicle = LocalPlayer():GlideGetVehicle()
        if not IsValid(vehicle) or not vehicle.WTCockpitModels or not first_person(vehicle) then return end
        next_display_update = RealTime() + 0.05
        display_rendering = true
        for _, data in ipairs(display_data) do
            render.PushRenderTarget(data.rt)
            render.Clear(2, 6, 5, 255, true, true)
            cam.Start2D()
            local ok, err = pcall(draw_mfd, vehicle, data)
            cam.End2D()
            render.PopRenderTarget()
            if not ok then ErrorNoHalt("Cockpit display: " .. tostring(err) .. "\n") end
        end
        display_rendering = false
    end)

    local function draw_displays(vehicle)
        for _, data in ipairs(display_data) do
            render.SetMaterial(data.material_rt)
            -- Draw both windings without changing global cull state.
            mesh.Begin(MATERIAL_TRIANGLES, #data.triangles * 2)
            for _, triangle in ipairs(data.triangles) do
                for _, index in ipairs({1, 2, 3, 3, 2, 1}) do
                    local vertex = triangle[index]
                    local u = (vertex[4] - data.uv[1]) / data.uv[3]
                    local v = 1 - (vertex[5] - data.uv[2]) / data.uv[4]
                    mesh.Position(vehicle:LocalToWorld(Vector(vertex[1], vertex[2], vertex[3])))
                    mesh.TexCoord(0, u, v)
                    mesh.Color(255, 255, 255, 255)
                    mesh.AdvanceVertex()
                end
            end
            mesh.End()
        end
    end

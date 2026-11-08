-- Run clientside through GTerm after installing volume.lua and both VCS files.
local drawVolume = include("wt_mig29_volume/volume.lua")
local rt = GetRenderTarget("dae_volume_gpu_test_v1", 256, 256)
local black = CreateMaterial("dae_volume_test_occluder_v2", "UnlitGeneric", { ["$basetexture"] = "color/white", ["$color"] = "[0 0 0]" })
local cases = {
    { Name = "side", Eye = Vector(-200, -300, 0), Target = Vector(-200, 0, 0), Power = 1 },
    { Name = "sideClose", Eye = Vector(-140, -140, 0), Target = Vector(-140, 0, 0), Power = 1 },
    { Name = "rear", Eye = Vector(-600, 0, 0), Target = Vector(0, 0, 0), Power = 1 },
    { Name = "oblique", Eye = Vector(-450, -240, 80), Target = Vector(-200, 0, 0), Power = 1 },
    { Name = "inside", Eye = Vector(-100, 0, 0), Target = Vector(-400, 0, 0), Power = 1 },
    { Name = "partial", Eye = Vector(-100, -300, 0), Target = Vector(-100, 0, 0), Power = 0.5 },
    { Name = "animated", Eye = Vector(-200, -300, 0), Target = Vector(-200, 0, 0), Power = 1, Time = 0.37 },
    { Name = "off", Eye = Vector(-200, -300, 0), Target = Vector(-200, 0, 0), Power = 0 },
    { Name = "occluded", Eye = Vector(-200, -300, 0), Target = Vector(-200, 0, 0), Power = 1, Occlude = true }
}
hook.Add("PostRender", "DAEVolumeGPUCheck", function()
    hook.Remove("PostRender", "DAEVolumeGPUCheck")
    local results = {}
    for _, case in ipairs(cases) do
        render.PushRenderTarget(rt)
        render.Clear(0, 0, 0, 255, true, true)
        cam.Start3D(case.Eye, (case.Target - case.Eye):Angle(), 70, 0, 0, 256, 256, 0.1, 3000)
        if case.Occlude then
            render.SetMaterial(black)
            render.DrawQuadEasy(Vector(-200, -100, 0), Vector(0, -1, 0), 1000, 1000, Color(0, 0, 0))
        end
        drawVolume(vector_origin, angle_zero, case.Power, case.Time or 0, case.Eye)
        cam.End3D()
        render.CapturePixels()
        local energy, lit, white = 0, 0, 0
        local peaks, continuity = 0, 1
        if case.Name == "side" or case.Name == "sideClose" or case.Name == "animated" then
            local profile = {}
            for x = 0, 255 do
                local sum = 0
                for y = 0, 255 do
                    local r, g, b = render.ReadPixel(x, y)
                    sum = sum + r + g + b
                end
                profile[x] = sum
            end
            -- Compare local troughs to nearby light, not to the naturally fading tail.
            local view = (case.Target - case.Eye):Angle()
            for distance = 40, 140, 2 do
                local relative = Vector(-distance, 0, 0) - case.Eye
                local x = math.floor(128 + relative:Dot(view:Right()) * 128 / (relative:Dot(view:Forward()) * math.tan(math.rad(35))))
                local peak = 1
                for offset = -8, 8 do
                    peak = math.max(peak, profile[math.Clamp(x + offset, 0, 255)])
                end
                continuity = math.min(continuity, profile[math.Clamp(x, 0, 255)] / peak)
            end
            for x = 3, 252 do
                if profile[x] > 100 and profile[x] > profile[x - 1] and profile[x] >= profile[x + 1]
                    and profile[x] > math.min(profile[x - 3], profile[x + 3]) * 1.25 then
                    peaks = peaks + 1
                end
            end
        end
        for y = 0, 255, 4 do
            for x = 0, 255, 4 do
                local r, g, b = render.ReadPixel(x, y)
                energy = energy + r + g + b
                if r + g + b > 3 then lit = lit + 1 end
                if r > 245 and g > 245 and b > 245 then white = white + 1 end
            end
        end
        file.Write("dae_volume_" .. case.Name .. ".png", render.Capture({ format = "png", x = 0, y = 0, w = 256, h = 256, alpha = false }))
        render.PopRenderTarget()
        results[case.Name] = { Energy = energy, Lit = lit, White = white, Peaks = peaks, Continuity = continuity }
    end
    print("DAE_VOLUME_GPU", util.TableToJSON(results))
    for _, name in ipairs({"side", "rear", "oblique", "inside", "partial", "animated"}) do
        assert(results[name].Energy > 100, name .. " volume missing")
    end
    for _, name in ipairs({"side", "sideClose", "animated"}) do
        assert(results[name].Continuity > 0.35, name .. " plume splits into isolated slices")
    end
    assert(results.rear.White < math.max(1, results.rear.Lit * 0.15), "rear volume clips to a white block")
    assert(results.partial.Energy < results.side.Energy, "partial throttle not dimmer")
    assert(results.animated.Energy ~= results.side.Energy, "noise did not animate")
    assert(results.off.Energy == 0, "engine-off volume visible")
    assert(results.occluded.Energy == 0, "volume visible through opaque wall")
    print("DAE_VOLUME_GPU_PASS")
end)

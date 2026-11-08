-- Client GPU readback: native nozzle mask and actual scene displacement.
local exhaust = include("wt_mig29_volume/exhaust.lua")
local rt = GetRenderTarget("dae_exhaust_gpu_v3", 512, 512)
local cases = {"baseline", "heat", "heatOff", "nozzle", "nozzleOff"}
hook.Add("PostRender", "DAEExhaustGPUCheck", function()
    hook.Remove("PostRender", "DAEExhaustGPUCheck")
    local results, baseline = {}, {}
    for _, name in ipairs(cases) do
        render.PushRenderTarget(rt)
        render.Clear(0, 0, 0, 255, true, true)
        if name == "baseline" or name == "heat" or name == "heatOff" then
            cam.Start2D()
            for y = 0, 511, 16 do
                for x = 0, 511, 16 do
                    local c = ((x+y)/16)%2 == 0 and 40 or 170
                    surface.SetDrawColor(c, c, c, 255)
                    surface.DrawRect(x, y, 16, 16)
                end
            end
            cam.End2D()
        end
        -- The test target is square; supply a same-sized scene texture.
        local scene = GetRenderTarget("dae_heat_scene_v3", 512, 512)
        render.CopyRenderTargetToTexture(scene)
        Material("!dae_wt_heat_v3"):SetTexture("$texture1", scene)
        local eye = Vector(-130, 0, 0)
        local view = (vector_origin - eye):Angle()
        cam.Start3D(eye, view, 60, 0, 0, 512, 512, 1, 2000)
        if name == "heat" or name == "heatOff" then
            exhaust.Heat(vector_origin, angle_zero, 16, name == "heat" and 1 or 0, 1, 0.21, view)
        elseif name == "nozzle" or name == "nozzleOff" then
            exhaust.Nozzle(vector_origin, angle_zero, 18, name == "nozzle" and 1 or 0, 0.21)
        end
        cam.End3D()
        render.CapturePixels()
        local energy, changed, peak, white, lit = 0, 0, 0, 0, 0
        local centre, annulus, centreCount, annulusCount = 0, 0, 0, 0
        for y = 0, 511, 2 do
            for x = 0, 511, 2 do
                local r, g, b = render.ReadPixel(x, y)
                local key = y*512+x
                if name == "baseline" then baseline[key] = r+g+b end
                if math.abs(r+g+b-(baseline[key] or 0)) > 6 then changed = changed+1 end
                energy = energy+r+g+b
                peak = math.max(peak, r, g, b)
                if r > 245 and g > 245 and b > 245 then white = white + 1 end
                if r + g + b > 3 then lit = lit + 1 end
                local radius = math.sqrt((x - 256)^2 + (y - 256)^2)
                if radius < 8 then
                    centre, centreCount = centre + r + g + b, centreCount + 1
                elseif radius > 22 and radius < 42 then
                    annulus, annulusCount = annulus + r + g + b, annulusCount + 1
                end
            end
        end
        results[name] = {Energy=energy, Changed=changed, Peak=peak, White=white, Lit=lit, Centre=centre / centreCount, Annulus=annulus / annulusCount}
        file.Write("dae_exhaust_"..name..".png", render.Capture({format="png", x=0, y=0, w=512, h=512, alpha=false}))
        render.PopRenderTarget()
    end
    Material("!dae_wt_heat_v3"):SetTexture("$texture1", render.GetScreenEffectTexture())
    print("DAE_EXHAUST_GPU", util.TableToJSON(results))
    assert(results.heat.Changed > 10, "heat does not displace scene")
    assert(results.heatOff.Changed == 0, "engine-off heat changes scene")
    assert(results.nozzle.Energy > 100, "native nozzle missing")
    assert(results.nozzleOff.Energy == 0, "engine-off nozzle visible")
    assert(results.nozzle.Peak > 210, "reference nozzle highlight missing")
    assert(results.nozzle.Annulus > results.nozzle.Centre * 1.5, "nozzle lost its dark centre")
    assert(results.nozzle.White < results.nozzle.Lit * 0.15, "whole nozzle clips to white")
    print("DAE_EXHAUST_GPU_PASS")
end)

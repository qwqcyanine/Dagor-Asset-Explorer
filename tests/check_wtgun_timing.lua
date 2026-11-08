-- Run after missileLua({}) with local ENT/BaseClass and a controllable CurTime.
local vehicle = setmetatable({weapons = {}, weaponState = {index = 1}}, {__index = ENT})
function vehicle:MarkWeaponDataAsDirty() end
function vehicle:CreateWeapon() error("Unexpected missile") end
vehicle:CreateFeatures()
for _, weapon in ipairs(vehicle.weapons) do
    for _, rate in ipairs({30, 60}) do
        weapon.FireDelay = 1 / rate
        weapon.nextFire = 0
        weapon.isFiring = false
        local shots, first, last = 0
        for tick = 1, 1000 do
            clock = tick * engine.TickInterval()
            if clock > weapon.nextFire then
                weapon:SetNextPrimaryFire(clock + weapon.FireDelay)
                weapon.isFiring = true
                shots = shots + 1
                first = first or clock
                last = clock
                if shots == 150 then break end
            end
        end
        assert(shots == 150)
        assert(math.abs(last - first - 149 / rate) < 2 * engine.TickInterval(), "Tick rounding slowed gun")
        clock = clock + 10
        weapon.isFiring = false
        weapon:SetNextPrimaryFire(clock + weapon.FireDelay)
        assert(math.abs(weapon.nextFire - clock - weapon.FireDelay) < 0.00001, "Idle burst debt")
        weapon.isFiring = true
        clock = clock + 10
        weapon:SetNextPrimaryFire(clock + weapon.FireDelay)
        assert(weapon.nextFire >= clock - engine.TickInterval(), "Unbounded lag catch-up")
    end
end
vehicle.weapons[2].ammo = 0
vehicle.weapons[2].MaxAmmo = 150
vehicle.weapons[2].nextReload = clock - 1
vehicle.weapons[2].isReloading = true
vehicle.weapons[2].Reload = function(self) self.ammo = self.MaxAmmo end
vehicle:WeaponThink(vehicle)
assert(vehicle.weapons[2].ammo == 150 and not vehicle.weapons[2].isReloading)
print("WT_GUN_TIMING_OK: 30/60Hz, idle, lag bound, holstered reload")

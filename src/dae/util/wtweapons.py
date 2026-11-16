"""Native aircraft ammunition, baseline arcade reloads and separable missile geometry."""
from pathlib import Path
import math
import re

from util.wtloadout import items


def reloadTime(blk, weapon, gameplay):
	definition = weapon.get("weaponBlk", {})
	trigger = weapon.get("trigger")
	kind = "bomb" if trigger == "bombs" else "rocket" if trigger in ("aam", "agm", "rockets") else "cannon" if definition.get("cannon") or trigger == "cannon" else "gun"
	key = kind + "ReloadCooldownTime"
	seconds = (gameplay.get(blk.get("type")) or {}).get(key, gameplay.get("common", {}).get(key))
	if kind in ("gun", "cannon"):
		bullet = items(definition.get("bullet"))
		caliber = bullet[0].get("caliber") if bullet else None
		for size, value in (gameplay.get("reloadCooldownTimeByCaliber") or {}).get("time", []):
			if caliber is not None and math.isclose(size, caliber, abs_tol=1e-6):
				seconds = value
				break
	if seconds is None or not math.isfinite(seconds) or seconds <= 0:
		raise ValueError(f"Missing WT arcade reload time: {weapon.get('blk')}")
	return float(seconds)


def ammoCount(weapon):
	value = weapon.get("bullets", weapon.get("weaponBlk", {}).get("bullets"))
	if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 65535 or int(value) != value:
		raise ValueError(f"Missing/invalid aircraft ammunition: {weapon.get('blk')}")
	return int(value)


def compileMissiles(qcPath, mounts):
	"""Build projectile models; heavy rocket loadouts render mounts outside the airframe."""
	qcPath = Path(qcPath)
	text = qcPath.read_text()
	model = re.search(r'\$modelname "([^"]+)\.mdl"', text)[1]
	targets = []
	externalLoadout = any(m.get("weapon", {}).get("trigger") == "rockets" for m in mounts)
	for mount in mounts:
		if "weapon" not in mount and not (externalLoadout and "mesh" in mount):
			continue
		prefix = mount["prefix"]
		pattern = re.compile(r'^\$body studio "([^"]*' + re.escape(prefix) + r'_[^"]+\.smd)"$', re.M)
		matches = list(pattern.finditer(text))
		if not matches:
			raise ValueError(f"Missing missile geometry: {prefix}")
		triangles, header = [], None
		for match in matches:
			smd = (qcPath.parent / match[1]).read_text()
			head, faces = smd.split("triangles\n", 1)
			if header is not None and head != header:
				raise ValueError(f"Missile skeleton mismatch: {prefix}")
			header = head
			triangles.extend(faces.rsplit("end", 1)[0].splitlines())
		merged = prefix + ".smd"
		(qcPath.parent / merged).write_text(header + "triangles\n" + "\n".join(triangles) + "\nend\n")
		group = f'$bodygroup "{prefix}"\n{{\n studio "{merged}"\n blank\n}}'
		# Populated pods exceed StudioMDL's mesh-index limit when baked into the airframe.
		mount["external"] = externalLoadout
		text = pattern.sub(lambda m: group if not mount["external"] and m.start() == matches[0].start() else "", text)
		# Keep the already corrected reflection and orientation; only move the origin to the emitter.
		x, y, z = mount["pos"]
		origin = (x, z, -y)  # Source -> SMD Y-up mirrored coordinates
		projectile = []
		for i, line in enumerate(triangles):
			if i % 4:
				fields = line.split()
				fields[0] = "0"
				fields[1:4] = [f"{float(fields[j + 1]) - origin[j]:.6f}" for j in range(3)]
				line = " ".join(fields[:9])
			projectile.append(line)
		name = f"{Path(model).name}_{prefix}"
		projectilePath = qcPath.parent / (name + ".smd")
		projectilePath.write_text('version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n' + "\n".join(projectile) + "\nend\n")
		projectileQC = qcPath.parent / (name + ".qc")
		materials = re.search(r'^\$cdmaterials .+$', text, re.M)[0]
		projectileModel = str(Path(model).parent / name).replace("\\", "/")
		projectileQC.write_text(f'$upaxis Y\n$origin 0 0 0 -90\n$modelname "{projectileModel}.mdl"\n{materials}\n$body studio "{name}.smd"\n$sequence idle "{name}.smd"\n')
		mount["model"] = "models/" + projectileModel + ".mdl"
		targets.append((projectileQC, name))
	qcPath.write_text(text)
	return targets


def aircraftWeaponBlocks(mounts, reloadTimes=None, *, guns=(), labels=None):
	"""Return structured Lua snippets for Glide's single CLIENT/SERVER vehicle definition."""
	import json
	groups = {}
	for mount in mounts:
		if "weapon" in mount:
			w = mount["weapon"]
			definition = w["weaponBlk"]
			projectile = definition.get("rocket") or definition.get("bomb") or {}
			groups.setdefault((w.get("trigger"), projectile.get("bulletName", w["blk"])), []).append(mount)
	reloadTimes = reloadTimes or {}
	for kind, seconds in reloadTimes.items():
		if kind not in ("gun", "missile", "bomb") or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= 3600:
			raise ValueError(f"Invalid reload override: {kind}={seconds}")
	from util.wtloadout import presetLabel
	weapons = [*guns, *(group[0]["weapon"] for group in groups.values())]
	# Match CreateFeatures order: built-in/pod guns first, then grouped missiles/bombs.
	info = [{"name": presetLabel({"Weapon": dict(w, bullets=1)}, labels or {})[0]} for w in weapons]
	weaponInfo = json.dumps(info, ensure_ascii=True).replace("]==]", "\\u005d==\\u005d")
	data = json.dumps(list(groups.values()), separators=(",", ":"))
	external = [m for m in mounts if m.get("external")]
	pods = {m["container"] for m in mounts if m.get("container")}
	if not pods.issubset({m["prefix"] for m in external}):
		raise ValueError("Rocket containers require independent shell models")

	clientSetup = ""
	clientDraw = ""
	clientCleanup = ""
	if external:
		mountsJson = json.dumps([dict({k: m[k] for k in ("prefix", "pos", "model")}, pod=m["prefix"] in pods) for m in external])
		clientSetup = f"    local MOUNTS = util.JSONToTable( [==[{mountsJson}]==] )"
		clientDraw = '''        self.wtMountedRockets = self.wtMountedRockets or {}
        self.wtDroppedPods = self.wtDroppedPods or {}

        for i, mount in ipairs( MOUNTS ) do
            if mount.pod and self:GetNW2Bool( mount.prefix, false ) then
                local model = self.wtMountedRockets[i]

                if IsValid( model ) then
                    self.wtDroppedPods[#self.wtDroppedPods + 1] = {
                        Model = model, Position = model:GetPos(), Angles = model:GetAngles(),
                        Velocity = self:GetVelocity() - self:GetUp() * 40, Time = CurTime()
                    }
                    self.wtMountedRockets[i] = nil
                end
            end

            if not self:GetNW2Bool( mount.prefix, false ) then
                local model = self.wtMountedRockets[i]

                if not IsValid( model ) then
                    model = ClientsideModel( mount.model, RENDERGROUP_OPAQUE )
                    if IsValid( model ) then model:SetNoDraw( true ) end
                    self.wtMountedRockets[i] = model
                end

                if IsValid( model ) then
                    local p = mount.pos
                    model:SetPos( self:LocalToWorld( Vector( p[1], p[2], p[3] ) ) )
                    model:SetAngles( self:GetAngles() )
                    model:SetSkin( self:GetSkin() )
                    model:SetupBones()
                    model:DrawModel()
                end
            end
        end

        -- Cosmetic debris: no collision forces or extra server entities on the aircraft.
        for i = #self.wtDroppedPods, 1, -1 do
            local pod = self.wtDroppedPods[i]
            local age = CurTime() - pod.Time

            if age > 8 or not IsValid( pod.Model ) then
                if IsValid( pod.Model ) then pod.Model:Remove() end
                table.remove( self.wtDroppedPods, i )
            else
                pod.Model:SetPos( pod.Position + pod.Velocity * age - Vector( 0, 0, 0.5 * 9.80665 * 40 * age * age ) )
                pod.Model:SetAngles( pod.Angles + Angle( age * 12, 0, age * 8 ) )
                pod.Model:SetupBones()
                pod.Model:DrawModel()
            end
        end'''
		clientCleanup = '''        for _, pod in ipairs( self.wtDroppedPods or {} ) do
            if IsValid( pod.Model ) then pod.Model:Remove() end
        end

        self.wtDroppedPods = nil

        for _, model in pairs( self.wtMountedRockets or {} ) do
            if IsValid( model ) then model:Remove() end
        end

        self.wtMountedRockets = nil'''

	serverSetupParts = []
	if groups:
		serverSetupParts.append(f"    local missileGroups = util.JSONToTable( [==[{data}]==] )")
	if reloadTimes or groups:
		serverSetupParts.append(f"    local reloadTimes = util.JSONToTable( [==[{json.dumps(reloadTimes)}]==] )")
	serverSetup = "\n".join(serverSetupParts)

	createFeatureParts = []
	if groups or reloadTimes:
		createFeatureParts.append('''        for _, weapon in ipairs( self.weapons ) do
            if weapon.ClassName == "base" or weapon.ClassName == "explosive_cannon" then
                weapon.ReloadDelay = reloadTimes.gun or weapon.ReloadDelay

                -- shortcut: preserve sub-tick remainder, but >tick-rate guns need multi-shot scheduling.
                function weapon:SetNextPrimaryFire( time )
                    self.nextFire = self.isFiring and math.max( self.nextFire, CurTime() - engine.TickInterval() ) + self.FireDelay or time
                end
            end
        end''')

	if groups:
		createFeatureParts.append('''        for _, mounts in ipairs( missileGroups ) do
            local definition = mounts[1].weapon.weaponBlk
            local isBomb = definition.bomb ~= nil
            local guided = not isBomb and ( mounts[1].weapon.trigger ~= "rockets" or definition.rocket.guidanceType ~= nil )

            self:CreateWeapon( guided and "homing_launcher" or "missile_launcher", {
                MaxAmmo = #mounts,
                ReloadDelay = reloadTimes[isBomb and "bomb" or "missile"] or mounts[1].weapon.arcadeReload,
                FireDelay = 1 / math.max( definition.shotFreq or 1, 0.01 )
            } )

            local weapon = self.weapons[self.weaponCount]
            weapon.WTMounts = mounts
            local reload = weapon.Reload

            function weapon:Reload()
                reload( self )
                self.isReloading = false
                self.projectileOffsetIndex = 0

                for _, mount in ipairs( self.WTMounts ) do
                    if mount.container then self.Vehicle:SetNW2Bool( mount.container, false ) end

                    if mount.external then
                        self.Vehicle:SetNW2Bool( mount.prefix, false )
                    else
                        self.Vehicle:SetBodygroup( self.Vehicle:FindBodygroupByName( mount.prefix ), 0 )
                    end
                end
            end

            function weapon:Think()
                if not self.Vehicle:GetInputBool( 1, "attack" ) then
                    self.WTTriggerHeld = false
                end
            end

            function weapon:PrimaryAttack()
                if self.WTTriggerHeld then return end
                self.WTTriggerHeld = true

                local vehicle = self.Vehicle
                local index = self.projectileOffsetIndex + 1
                local mount = self.WTMounts[index]
                if not mount then return end

                local target = guided and vehicle:GetLockOnState() == 2 and vehicle:GetLockOnTarget() or nil
                local p = mount.pos
                local pos = vehicle:LocalToWorld( Vector( p[1], p[2], p[3] ) )
                local missile

                if isBomb then
                    missile = ents.Create( "glide_projectile" )
                    if not IsValid( missile ) then return end

                    missile:SetPos( pos )
                    missile:SetAngles( vehicle:GetAngles() )
                    missile:Spawn()
                    missile:SetupProjectile( vehicle:GetSeatDriver( 1 ), vehicle )
                    missile:SetModel( mount.model )
                    missile.velocity = vehicle:GetVelocity()
                    missile:SetProjectileGravity( 9.80665 * 40 )
                    missile.lifeTime = CurTime() + 120

                    local bomb = definition.bomb
                    local expMass = bomb.explosiveMass or 10
                    -- shortcut: Glide blast damage is an approximation, not WT fragment/penetration simulation.
                    missile.damage = math.max( 250, expMass * 10 )
                    missile.radius = math.min( 4000, 100 * expMass ^ ( 1 / 3 ) )

                    local phys = missile:GetPhysicsObject()
                    if IsValid( phys ) then phys:SetMass( bomb.mass ) end
                else
                    missile = vehicle:FireMissile( pos, vehicle:GetAngles(), vehicle:GetSeatDriver( 1 ), target )
                    if not IsValid( missile ) then return end

                    missile:SetModel( mount.model )
                    local rocket = mount.weapon.weaponBlk.rocket
                    -- Unguided WT rockets may specify range instead of a lifetime.
                    local lifetime = rocket.timeLife or rocket.maxDistance * 40 / math.min( 4000, rocket.endSpeed * 40 )
                    missile.lifeTime = CurTime() + lifetime
                    -- shortcut: Glide physics caps speed and approximates WT propulsion/guidance; not a WT flight solver.
                    missile.maxSpeed = math.min( 4000, rocket.endSpeed * 40 )
                    missile.acceleration = rocket.force / rocket.mass * 40
                    missile.speed = math.max( rocket.startSpeed * 40, vehicle:GetVelocity():Dot( vehicle:GetForward() ) )

                    local phys = missile:GetPhysicsObject()
                    if IsValid( phys ) then phys:SetMass( rocket.mass ) end
                end

                self:TakePrimaryAmmo( 1 )
                self:SetNextPrimaryFire( CurTime() + self.FireDelay )
                self.projectileOffsetIndex = index

                if mount.external then
                    vehicle:SetNW2Bool( mount.prefix, true )
                else
                    vehicle:SetBodygroup( vehicle:FindBodygroupByName( mount.prefix ), 1 )
                end

                if mount.container then
                    local empty = true

                    for _, group in ipairs( missileGroups ) do
                        for _, round in ipairs( group ) do
                            if round.container == mount.container and not vehicle:GetNW2Bool( round.prefix, false ) then
                                empty = false
                            end
                        end
                    end

                    if empty then vehicle:SetNW2Bool( mount.container, true ) end
                end
            end
        end''')

	serverCreateFeatures = "\n\n".join(createFeatureParts)

	serverWeaponThink = '''    -- Glide only thinks the active weapon; finish holstered reloads as well.
    function ENT:WeaponThink( selfTbl )
        for index, weapon in ipairs( self.weapons ) do
            if weapon.WTMounts and not self:GetInputBool( 1, "attack" ) then
                weapon.WTTriggerHeld = false
            end

            if index ~= self.weaponState.index and weapon.MaxAmmo > 0 and weapon.ammo == 0 and CurTime() > weapon.nextReload then
                weapon:Reload()
                weapon.isReloading = false
                self:MarkWeaponDataAsDirty()
            end
        end

        BaseClass.WeaponThink( self, selfTbl )
    end''' if (groups or guns) else ""

	return {
		"weaponInfo": f"ENT.WeaponInfo = util.JSONToTable( [==[{weaponInfo}]==] )" if info else "",
		"clientSetup": clientSetup,
		"clientDraw": clientDraw,
		"clientCleanup": clientCleanup,
		"serverSetup": serverSetup,
		"serverCreateFeatures": serverCreateFeatures,
		"serverWeaponThink": serverWeaponThink,
	}

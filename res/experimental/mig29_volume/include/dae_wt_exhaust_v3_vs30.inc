#pragma once
#include "shaderlib/cshader.h"
class dae_wt_exhaust_v3_vs30_Static_Index
{
public:
	dae_wt_exhaust_v3_vs30_Static_Index( IShaderShadow* pShaderShadow, IMaterialVar** params )
	{
	}

	int GetIndex() const
	{
		return 0;
	}
};

#define shaderStaticTest_dae_wt_exhaust_v3_vs30 1


class dae_wt_exhaust_v3_vs30_Dynamic_Index
{
public:
	dae_wt_exhaust_v3_vs30_Dynamic_Index( IShaderDynamicAPI* pShaderAPI )
	{
	}

	int GetIndex() const
	{
		return 0;
	}
};

#define shaderDynamicTest_dae_wt_exhaust_v3_vs30 1
